"""Best-effort Telegram alerts for critical backend failures."""

from __future__ import annotations

import logging
import traceback

import httpx
from fastapi import Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_TELEGRAM_MAX_MESSAGE = 4096
_MESSAGE_CHUNK_SIZE = 3900


async def notify_critical_500(request: Request, exc: Exception) -> None:
    """Send traceback details to the configured Telegram bot, if enabled."""

    settings = get_settings()
    token = (
        settings.telegram_error_bot_token.get_secret_value().strip()
        if settings.telegram_error_bot_token is not None
        else ""
    )
    chat_id = (settings.telegram_error_chat_id or "").strip()
    if not token or not chat_id:
        return

    message = _format_alert(request, exc)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = httpx.Timeout(settings.telegram_error_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for chunk in _chunks(message):
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
    except Exception:
        logger.warning("Telegram critical error alert failed", exc_info=True)


def _format_alert(request: Request, exc: Exception) -> str:
    client_host = request.client.host if request.client is not None else "unknown"
    traceback_text = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return (
        "AI-Card-Master critical 500\n"
        f"method: {request.method}\n"
        f"path: {request.url.path}\n"
        f"client: {client_host}\n"
        f"exception: {type(exc).__name__}: {exc}\n\n"
        f"{traceback_text}"
    )


def _chunks(message: str) -> tuple[str, ...]:
    if len(message) <= _TELEGRAM_MAX_MESSAGE:
        return (message,)
    return tuple(
        message[index : index + _MESSAGE_CHUNK_SIZE]
        for index in range(0, len(message), _MESSAGE_CHUNK_SIZE)
    )
