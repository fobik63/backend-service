"""Telegram webhook secret must be compared with hmac.compare_digest."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.telegram_bot import telegram_webhook


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/telegram/webhook",
            "raw_path": b"/api/v1/telegram/webhook",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("1.1.1.1", 443),
            "server": ("test", 443),
        }
    )


@pytest.mark.asyncio
async def test_production_rejects_empty_telegram_webhook_secret() -> None:
    request = _request()
    with patch(
        "app.api.telegram_bot.get_settings",
        return_value=SimpleNamespace(
            app_env="production",
            telegram_bot_webhook_secret="",
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await telegram_webhook(request, x_telegram_bot_api_secret_token=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_telegram_secret_mismatch_is_rejected() -> None:
    request = _request()
    with patch(
        "app.api.telegram_bot.get_settings",
        return_value=SimpleNamespace(
            app_env="development",
            telegram_bot_webhook_secret="expected-secret",
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await telegram_webhook(
                request,
                x_telegram_bot_api_secret_token="wrong-secret",
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_telegram_secret_match_processes_update() -> None:
    request = _request()
    with (
        patch(
            "app.api.telegram_bot.get_settings",
            return_value=SimpleNamespace(
                app_env="production",
                telegram_bot_webhook_secret="expected-secret",
            ),
        ),
        patch.object(
            Request,
            "json",
            AsyncMock(return_value={"update_id": 1}),
        ),
        patch(
            "app.api.telegram_bot.process_telegram_update",
            new=AsyncMock(),
        ) as process,
    ):
        result = await telegram_webhook(
            request,
            x_telegram_bot_api_secret_token="expected-secret",
        )
    assert result == {"ok": True}
    process.assert_awaited_once()
