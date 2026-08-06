"""Best-effort Telegram alerts for backend failures (plan §16).

Every alert includes explicit ``error_type``, ``file``, and ``line`` fields
so operators can jump to the failing code without parsing a full traceback.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request

from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings

logger = logging.getLogger(__name__)
_TELEGRAM_MAX_MESSAGE = 4096
_MESSAGE_CHUNK_SIZE = 3900


@dataclass(frozen=True, slots=True)
class ErrorLocation:
    """Resolved source location for an exception or log record."""

    filename: str
    lineno: int
    func_name: str

    @property
    def short_filename(self) -> str:
        normalized = self.filename.replace("\\", "/")
        marker = "/app/"
        if marker in normalized:
            return "app/" + normalized.split(marker, 1)[1]
        return normalized.rsplit("/", 1)[-1]


def extract_error_location(exc: BaseException) -> ErrorLocation:
    """Prefer the deepest frame under ``app/``; fall back to the last frame."""

    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    app_frame: traceback.FrameSummary | None = None
    for frame in frames:
        normalized = frame.filename.replace("\\", "/")
        if "/app/" in normalized:
            app_frame = frame
    chosen = app_frame or (frames[-1] if frames else None)
    if chosen is None:
        return ErrorLocation(filename="unknown", lineno=0, func_name="unknown")
    return ErrorLocation(
        filename=chosen.filename,
        lineno=int(chosen.lineno or 0),
        func_name=chosen.name or "unknown",
    )


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

    message = _format_http_alert(request, exc)
    await _send_telegram_async(token=token, chat_id=chat_id, message=message)


async def notify_error(
    *,
    error_type: str,
    message: str,
    location: ErrorLocation,
    context: dict[str, Any] | None = None,
    traceback_text: str | None = None,
) -> None:
    """Notify operator about any error with explicit file:line + type."""

    settings = get_settings()
    token = (
        settings.telegram_error_bot_token.get_secret_value().strip()
        if settings.telegram_error_bot_token is not None
        else ""
    )
    chat_id = (settings.telegram_error_chat_id or "").strip()
    if not token or not chat_id:
        return

    lines = [
        "AI-Card-Master ERROR",
        f"error_type: {error_type}",
        f"file: {location.short_filename}",
        f"line: {location.lineno}",
        f"function: {location.func_name}",
        f"message: {message}",
    ]
    if context:
        for key, value in context.items():
            lines.append(f"{key}: {value}")
    if traceback_text:
        lines.append("")
        lines.append(traceback_text)
    await _send_telegram_async(
        token=token,
        chat_id=chat_id,
        message="\n".join(lines),
    )


def notify_error_sync(
    *,
    error_type: str,
    message: str,
    location: ErrorLocation,
    context: dict[str, Any] | None = None,
    traceback_text: str | None = None,
) -> None:
    """Synchronous Telegram send for Celery workers / logging handlers."""

    settings = get_settings()
    token = (
        settings.telegram_error_bot_token.get_secret_value().strip()
        if settings.telegram_error_bot_token is not None
        else ""
    )
    chat_id = (settings.telegram_error_chat_id or "").strip()
    if not token or not chat_id:
        return

    lines = [
        "AI-Card-Master ERROR",
        f"error_type: {error_type}",
        f"file: {location.short_filename}",
        f"line: {location.lineno}",
        f"function: {location.func_name}",
        f"message: {message}",
    ]
    if context:
        for key, value in context.items():
            lines.append(f"{key}: {value}")
    if traceback_text:
        lines.append("")
        lines.append(traceback_text)
    _send_telegram_sync(token=token, chat_id=chat_id, message="\n".join(lines))


def _format_http_alert(request: Request, exc: Exception) -> str:
    settings = get_settings()
    client_host = getattr(request.state, "client_ip", None) or resolve_client_ip(
        request,
        trust_cloudflare=settings.cloudflare_trust_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )
    location = extract_error_location(exc)
    traceback_text = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return (
        "AI-Card-Master critical 500\n"
        f"error_type: {type(exc).__name__}\n"
        f"file: {location.short_filename}\n"
        f"line: {location.lineno}\n"
        f"function: {location.func_name}\n"
        f"method: {request.method}\n"
        f"path: {request.url.path}\n"
        f"client: {client_host}\n"
        f"message: {exc}\n\n"
        f"{traceback_text}"
    )


async def _send_telegram_async(*, token: str, chat_id: str, message: str) -> None:
    settings = get_settings()
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


def _send_telegram_sync(*, token: str, chat_id: str, message: str) -> None:
    settings = get_settings()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = httpx.Timeout(settings.telegram_error_timeout_seconds)
    try:
        with httpx.Client(timeout=timeout) as client:
            for chunk in _chunks(message):
                response = client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
    except Exception:
        logger.warning("Telegram sync error alert failed", exc_info=True)


def _chunks(message: str) -> tuple[str, ...]:
    if len(message) <= _TELEGRAM_MAX_MESSAGE:
        return (message,)
    return tuple(
        message[index : index + _MESSAGE_CHUNK_SIZE]
        for index in range(0, len(message), _MESSAGE_CHUNK_SIZE)
    )
