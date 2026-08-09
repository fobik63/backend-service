"""Best-effort product event notifications via the user Telegram bot."""

from __future__ import annotations

import logging
from uuid import UUID

from app.domain.telegram_bot import (
    message_pack_generated,
    message_publish_error,
    message_publish_success,
)
from app.infrastructure.persistence.telegram_bot_repository import TelegramBotUserRepository
from app.models.database import SessionLocal
from app.services.telegram_user_notify import TelegramUserNotifier

logger = logging.getLogger(__name__)


async def notify_user_telegram(*, user_id: UUID, text: str) -> bool:
    """Send a Telegram message when the user has linked chat id."""

    try:
        async with SessionLocal() as session:
            repo = TelegramBotUserRepository(session)
            chat_id = await repo.get_telegram_id(user_id)
            if chat_id is None:
                return False
            return await TelegramUserNotifier().send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.warning("Telegram product notify failed user_id=%s", user_id, exc_info=True)
        return False


async def notify_publish_success(
    *,
    user_id: UUID,
    platform: str,
    product_id: str,
) -> bool:
    return await notify_user_telegram(
        user_id=user_id,
        text=message_publish_success(platform=platform, product_id=product_id),
    )


async def notify_publish_error(
    *,
    user_id: UUID,
    platform: str,
    product_id: str,
    detail: str | None = None,
) -> bool:
    return await notify_user_telegram(
        user_id=user_id,
        text=message_publish_error(
            platform=platform,
            product_id=product_id,
            detail=detail,
        ),
    )


async def notify_pack_generated(*, user_id: UUID, title: str | None = None) -> bool:
    return await notify_user_telegram(
        user_id=user_id,
        text=message_pack_generated(title=title),
    )
