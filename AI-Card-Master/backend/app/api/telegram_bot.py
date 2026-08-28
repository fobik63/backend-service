"""Telegram bot webhook + deep-link helpers for account binding."""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.telegram_bot_service import TelegramBotService
from app.core.config import get_settings
from app.infrastructure.telegram.update_parser import extract_bot_command
from app.infrastructure.telegram_bot_factory import build_telegram_bot_service
from app.models.database import SessionLocal, get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram-bot"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeepLinkResponse(StrictAPIModel):
    payload: str
    deep_link_url: str | None = None
    bot_username: str
    expires_in_seconds: int


def get_telegram_bot_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> TelegramBotService:
    return build_telegram_bot_service(db_session)


@router.get("/deep-link", response_model=DeepLinkResponse)
async def get_telegram_deep_link(
    current_user: User = Depends(get_current_user),
    service: TelegramBotService = Depends(get_telegram_bot_service),
) -> DeepLinkResponse:
    """Return a signed deep-link payload for /start account binding."""

    settings = get_settings()
    payload = service.create_deep_link_payload(current_user.id)
    return DeepLinkResponse(
        payload=payload,
        deep_link_url=service.deep_link_url(current_user.id),
        bot_username=settings.telegram_login_bot_username,
        expires_in_seconds=settings.telegram_bot_deep_link_ttl_seconds,
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
) -> dict[str, bool]:
    """Inbound Telegram Bot API webhook (set via setWebhook)."""

    settings = get_settings()
    expected = (settings.telegram_bot_webhook_secret or "").strip()
    supplied = (x_telegram_bot_api_secret_token or "").strip()

    if settings.app_env == "production" and not expected:
        logger.error("TELEGRAM_BOT_WEBHOOK_SECRET is required in production")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram webhook secret.",
        )

    if expected and not hmac.compare_digest(
        supplied.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram webhook secret.",
        )

    try:
        payload: Any = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )

    await process_telegram_update(payload)
    return {"ok": True}


async def process_telegram_update(update: dict[str, Any]) -> None:
    """Shared handler for webhook and long-polling paths."""

    command = extract_bot_command(update)
    if command is None or command.command is None:
        return

    async with SessionLocal() as session:
        service = build_telegram_bot_service(session)
        await service.handle_update_command(command)
