"""Factory helpers for Telegram bot use cases."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.telegram_bot_service import TelegramBotService
from app.core.config import get_settings
from app.infrastructure.persistence.telegram_bot_repository import TelegramBotUserRepository
from app.infrastructure.telegram.bot_client import TelegramBotApiClient
from app.services.telegram_user_notify import TelegramUserNotifier


def _signing_secret() -> str:
    settings = get_settings()
    token = (
        settings.telegram_user_bot_token.get_secret_value().strip()
        if settings.telegram_user_bot_token is not None
        else ""
    )
    if token:
        return token
    return settings.jwt_secret_key.get_secret_value()


def build_telegram_bot_service(session: AsyncSession) -> TelegramBotService:
    settings = get_settings()
    return TelegramBotService(
        TelegramBotUserRepository(session),
        TelegramUserNotifier(),
        signing_secret=_signing_secret(),
        bot_username=settings.telegram_login_bot_username,
        deep_link_ttl_seconds=settings.telegram_bot_deep_link_ttl_seconds,
    )


def build_telegram_bot_api_client() -> TelegramBotApiClient:
    return TelegramBotApiClient()
