"""Best-effort Telegram alerts for backend failures (plan §16).

Critical 500 alerts are intentionally short: ``file``, ``line``, ``endpoint``,
and ``user_id`` so operators can triage quickly. Full traces go to Sentry.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import Request

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


def resolve_request_user_id(request: Request) -> str | None:
    """Best-effort user id from request state or Bearer JWT ``sub`` claim."""

    state = getattr(request, "state", None)
    if state is not None:
        for attr in ("user_id", "audit_user_id"):
            raw = getattr(state, attr, None)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text

    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    try:
        auth = headers.get("Authorization") or headers.get("authorization") or ""
    except Exception:
        return None
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    try:
        from app.core.security import decode_and_validate_token

        payload = decode_and_validate_token(token.strip(), expected_type="access")
    except Exception:
        return None

    subject = str(payload.get("sub") or "").strip()
    if not subject:
        return None
    try:
        return str(UUID(subject))
    except ValueError:
        return subject


async def notify_critical_500(request: Request, exc: Exception) -> None:
    """Send a short 500 alert to the configured Telegram admin chat via httpx."""

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
    """Short operator alert: file, line, endpoint, user_id (+ error type)."""

    location = extract_error_location(exc)
    user_id = resolve_request_user_id(request) or "anonymous"
    endpoint = f"{request.method} {request.url.path}"
    error_line = str(exc).strip() or type(exc).__name__
    if len(error_line) > 240:
        error_line = error_line[:237] + "..."
    return (
        "AI-Card-Master 500\n"
        f"file: {location.short_filename}\n"
        f"line: {location.lineno}\n"
        f"endpoint: {endpoint}\n"
        f"user_id: {user_id}\n"
        f"error: {type(exc).__name__}: {error_line}"
    )


async def send_operator_telegram(message: str) -> None:
    """Best-effort alert to the operator Telegram chat (no exception traceback)."""

    settings = get_settings()
    token = (
        settings.telegram_error_bot_token.get_secret_value().strip()
        if settings.telegram_error_bot_token is not None
        else ""
    )
    chat_id = (settings.telegram_error_chat_id or "").strip()
    if not token or not chat_id:
        logger.warning("Operator Telegram not configured; alert skipped")
        return
    await _send_telegram_async(token=token, chat_id=chat_id, message=message)


async def notify_security_ban(
    *,
    ip: str,
    reason: str,
    path: str,
    ttl_seconds: int,
    cloudflare_banned: bool = False,
    api_key_fingerprint: str | None = None,
) -> None:
    """Notify admin about an automatic Great Wall IP / API-key ban."""

    lines = [
        "AI-Card-Master SECURITY BAN (Great Wall)",
        f"ip: {ip}",
        f"reason: {reason}",
        f"path: {path}",
        f"ttl_seconds: {ttl_seconds}",
        f"cloudflare_banned: {cloudflare_banned}",
    ]
    if api_key_fingerprint:
        lines.append(f"api_key_fp: {api_key_fingerprint[:12]}…")
    await send_operator_telegram("\n".join(lines))


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
