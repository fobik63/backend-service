"""User-facing Telegram messages for Win-back / retention triggers."""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_TELEGRAM_MAX_MESSAGE = 4096


class TelegramUserNotifier:
    """Best-effort Telegram Bot API sender for product trigger messages."""

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        """Send a plain-text message; return False when disabled or on failure."""

        settings = get_settings()
        token = (
            settings.telegram_user_bot_token.get_secret_value().strip()
            if settings.telegram_user_bot_token is not None
            else ""
        )
        if not token:
            # Fall back to the ops error bot when a dedicated user bot is unset.
            token = (
                settings.telegram_error_bot_token.get_secret_value().strip()
                if settings.telegram_error_bot_token is not None
                else ""
            )
        if not token or chat_id == 0:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        timeout = httpx.Timeout(settings.telegram_user_timeout_seconds)
        payload_text = text if len(text) <= _TELEGRAM_MAX_MESSAGE else text[:_TELEGRAM_MAX_MESSAGE]
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": payload_text,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
            return True
        except Exception:
            logger.warning(
                "Telegram user message failed chat_id=%s",
                chat_id,
                exc_info=True,
            )
            return False
