"""Application façade for Midjourney / async provider webhooks (audit A2)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

from app.application.ports.image_generation import AsyncImageProviderPort
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.services.ai_engine import AIEngineValidationError

logger = logging.getLogger(__name__)


class MidjourneyWebhookIngressService:
    """Authenticate, normalise, and persist provider callbacks."""

    def __init__(
        self,
        *,
        repository: GenerationRepository,
        provider_resolver: Any,
    ) -> None:
        self._repository = repository
        self._resolve_provider = provider_resolver

    def resolve_provider(self, provider_name: str) -> AsyncImageProviderPort | None:
        return self._resolve_provider(provider_name)

    def verify(
        self,
        provider: AsyncImageProviderPort,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        callback_token: str | None,
    ) -> bool:
        return provider.verify_webhook(
            headers=headers,
            raw_body=raw_body,
            callback_token=callback_token,
        )

    def parse_json(self, raw_body: bytes) -> dict[str, Any]:
        import json

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise AIEngineValidationError("Webhook body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise AIEngineValidationError("Webhook body must be a JSON object.")
        return payload

    async def accept(
        self,
        *,
        provider: AsyncImageProviderPort,
        payload: dict[str, Any],
        raw_body: bytes,
        safe_payload: Mapping[str, Any],
    ) -> tuple[Any, bool]:
        """Persist the normalised event; return (event_row, already_processed)."""

        event = provider.parse_webhook(payload)
        event = event.model_copy(update={"raw_payload": dict(safe_payload)})
        return await self._repository.store_webhook_event(
            event=event,
            payload_hash=hashlib.sha256(raw_body).hexdigest(),
            raw_payload=safe_payload,
        )
