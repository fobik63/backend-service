"""Telegram Bot API client: sendMessage, getUpdates, setWebhook."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_TELEGRAM_MAX_MESSAGE = 4096


def resolve_telegram_bot_token() -> str:
    """Prefer dedicated user bot token, then login / error bot fallbacks."""

    settings = get_settings()
    for attr in (
        "telegram_user_bot_token",
        "telegram_login_bot_token",
        "telegram_error_bot_token",
    ):
        secret = getattr(settings, attr, None)
        if secret is None:
            continue
        value = secret.get_secret_value().strip()
        if value:
            return value
    return ""


class TelegramBotApiClient:
    """Thin async wrapper around https://api.telegram.org/bot<token>/…"""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._token = (token if token is not None else resolve_telegram_bot_token()).strip()
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(settings.telegram_user_timeout_seconds)
        )
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        if not self._token or chat_id == 0:
            return False
        payload_text = text if len(text) <= _TELEGRAM_MAX_MESSAGE else text[:_TELEGRAM_MAX_MESSAGE]
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("sendMessage"),
                    json={
                        "chat_id": chat_id,
                        "text": payload_text,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
            return True
        except Exception:
            logger.warning("Telegram sendMessage failed chat_id=%s", chat_id, exc_info=True)
            return False

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 25,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self._token:
            return []
        payload: dict[str, Any] = {
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        try:
            async with self._http(timeout=float(timeout + 10)) as client:
                response = await client.post(self._url("getUpdates"), json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception:
            logger.warning("Telegram getUpdates failed", exc_info=True)
            return []
        if not isinstance(body, dict) or not body.get("ok"):
            return []
        result = body.get("result")
        return result if isinstance(result, list) else []

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = False,
    ) -> bool:
        if not self._token:
            return False
        payload: dict[str, Any] = {
            "url": url,
            "allowed_updates": ["message"],
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        try:
            async with self._http() as client:
                response = await client.post(self._url("setWebhook"), json=payload)
                response.raise_for_status()
            return True
        except Exception:
            logger.warning("Telegram setWebhook failed", exc_info=True)
            return False

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> bool:
        if not self._token:
            return False
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("deleteWebhook"),
                    json={"drop_pending_updates": drop_pending_updates},
                )
                response.raise_for_status()
            return True
        except Exception:
            logger.warning("Telegram deleteWebhook failed", exc_info=True)
            return False

    def _http(self, timeout: float | None = None) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=timeout if timeout is not None else self._timeout)


class _NullContextClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None
