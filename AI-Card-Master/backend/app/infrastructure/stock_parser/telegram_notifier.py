"""Telegram alerts for stock-parser circuit-breaker trips (ops admin only)."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from app.core.config import Settings
from app.domain.stock_parser import ParserErrorKind, ParserMarketplace

logger = logging.getLogger(__name__)
_TELEGRAM_MAX_MESSAGE = 4096
_MESSAGE_CHUNK_SIZE = 3900


class StockParserTelegramNotifier:
    """Send broken-parser Traceback alerts to TELEGRAM_ERROR_* admin chat."""

    def __init__(self, settings: Settings) -> None:
        self._token = (
            settings.telegram_error_bot_token.get_secret_value().strip()
            if settings.telegram_error_bot_token is not None
            else ""
        )
        self._chat_id = (settings.telegram_error_chat_id or "").strip()
        self._timeout = httpx.Timeout(settings.telegram_error_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def send_broken_alert(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        consecutive_errors: int,
        health_id: UUID,
    ) -> bool:
        if not self.enabled:
            logger.warning(
                "Parser broken alert skipped (Telegram not configured) "
                "marketplace=%s kind=%s",
                marketplace.value,
                error_kind.value,
            )
            return False

        message = (
            "AI-Card-Master stock-parser BROKEN\n"
            f"marketplace: {marketplace.value}\n"
            f"health_id: {health_id}\n"
            f"consecutive_errors: {consecutive_errors}\n"
            f"error_kind: {error_kind.value}\n"
            f"error: {error_message}\n\n"
            f"{traceback_text}"
        )
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for chunk in _chunks(message):
                    response = await client.post(
                        url,
                        json={
                            "chat_id": self._chat_id,
                            "text": chunk,
                            "disable_web_page_preview": True,
                        },
                    )
                    response.raise_for_status()
            return True
        except Exception:
            logger.warning(
                "Stock parser Telegram broken alert failed marketplace=%s",
                marketplace.value,
                exc_info=True,
            )
            return False


def _chunks(message: str) -> tuple[str, ...]:
    if len(message) <= _TELEGRAM_MAX_MESSAGE:
        return (message,)
    return tuple(
        message[index : index + _MESSAGE_CHUNK_SIZE]
        for index in range(0, len(message), _MESSAGE_CHUNK_SIZE)
    )
