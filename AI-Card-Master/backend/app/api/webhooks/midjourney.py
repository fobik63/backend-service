"""Authenticated, idempotent webhook ingress for async image providers."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.midjourney_webhook_service import MidjourneyWebhookIngressService
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.database import get_db_session
from app.services.ai_engine import (
    AIEngineValidationError,
    get_async_midjourney_provider,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks/midjourney", tags=["webhooks"])
MAX_WEBHOOK_BYTES = 1024 * 1024


class WebhookAck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    success: bool = True
    accepted: bool = True
    already_processed: bool = False


def get_midjourney_webhook_service(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MidjourneyWebhookIngressService:
    return MidjourneyWebhookIngressService(
        repository=GenerationRepository(db_session),
        provider_resolver=get_async_midjourney_provider,
    )


@router.post("/{provider_name}", response_model=WebhookAck)
async def receive_midjourney_webhook(
    provider_name: str,
    request: Request,
    service: Annotated[
        MidjourneyWebhookIngressService, Depends(get_midjourney_webhook_service)
    ],
    callback_token: Annotated[str | None, Query(alias="token", max_length=512)] = None,
    content_length: Annotated[int | None, Header(alias="Content-Length", ge=0)] = None,
) -> WebhookAck:
    """Authenticate, normalise, persist, and acknowledge a provider callback."""

    if content_length is not None and content_length > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload is too large.",
        )
    provider = service.resolve_provider(provider_name)
    if provider is None:
        # Do not reveal configured provider names to unauthenticated callers.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found."
        )

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload is too large.",
        )
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not service.verify(
        provider,
        headers=headers,
        raw_body=raw_body,
        callback_token=callback_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = service.parse_json(raw_body)
    except AIEngineValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    try:
        safe_payload = _bounded_payload(payload)
        _stored, duplicate = await service.accept(
            provider=provider,
            payload=payload,
            raw_body=raw_body,
            safe_payload=safe_payload,
        )
    except AIEngineValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return WebhookAck(already_processed=duplicate)


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact common secret fields before retaining bounded troubleshooting data."""

    sensitive = {"token", "secret", "authorization", "api_key", "apikey", "signature"}

    def _clean(value: Any, *, depth: int) -> Any:
        if depth > 8:
            return "[truncated]"
        if isinstance(value, dict):
            return {
                str(key)[:128]: (
                    "[redacted]"
                    if str(key).lower() in sensitive
                    else _clean(item, depth=depth + 1)
                )
                for key, item in list(value.items())[:200]
            }
        if isinstance(value, list):
            return [_clean(item, depth=depth + 1) for item in value[:200]]
        if isinstance(value, str):
            return value[:4096]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:4096]

    cleaned = _clean(payload, depth=0)
    return cleaned if isinstance(cleaned, dict) else {}
