"""Unit tests for cascading slowapi rate-limit helpers."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from app.core.rate_limit import (
    _retry_after_seconds,
    get_client_ip_key,
    get_user_id_key,
    rate_limit_exceeded_handler,
)
from app.core.security import InvalidTokenError


def _request(
    *,
    path: str = "/api/v1/auth/login",
    headers: dict[str, str] | None = None,
    client_host: str = "203.0.113.10",
    state: dict[str, object] | None = None,
    app: object | None = None,
) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": (client_host, 443),
        "server": ("test", 80),
    }
    if app is not None:
        scope["app"] = app
    request = Request(scope)
    for key, value in (state or {}).items():
        setattr(request.state, key, value)
    return request


def test_get_client_ip_key_prefers_request_state() -> None:
    request = _request(state={"client_ip": "198.51.100.7"})
    assert get_client_ip_key(request) == "198.51.100.7"


def test_get_user_id_key_from_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid4())

    def _decode(token: str, expected_type: str | None = None) -> dict[str, str]:
        assert token == "good-token"
        assert expected_type == "access"
        return {"sub": user_id, "type": "access"}

    monkeypatch.setattr(
        "app.core.rate_limit.decode_and_validate_token",
        _decode,
    )
    request = _request(headers={"Authorization": "Bearer good-token"})
    assert get_user_id_key(request) == f"user:{user_id}"


def test_get_user_id_key_falls_back_to_ip_on_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _decode(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise InvalidTokenError("bad")

    monkeypatch.setattr(
        "app.core.rate_limit.decode_and_validate_token",
        _decode,
    )
    request = _request(
        headers={"Authorization": "Bearer bad"},
        state={"client_ip": "192.0.2.1"},
    )
    assert get_user_id_key(request) == "ip:192.0.2.1"


@pytest.mark.asyncio
async def test_rate_limit_exceeded_handler_json_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace(state=SimpleNamespace(limiter=None))
    request = _request(app=app)
    request.state.view_rate_limit = None

    limit = MagicMock()
    limit.error_message = "Rate limit exceeded"
    limit.limit = SimpleNamespace(GRANULARITY=SimpleNamespace(seconds=60))
    exc = RateLimitExceeded(limit)

    monkeypatch.setattr(
        "app.core.rate_limit._retry_after_seconds",
        lambda *_a, **_k: 42,
    )
    response = await rate_limit_exceeded_handler(request, exc)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    payload = json.loads(response.body)
    assert payload == {"error": "Rate limit exceeded", "retry_after_seconds": 42}


def test_retry_after_from_window_stats() -> None:
    reset_at = int(time.time()) + 17
    limiter = SimpleNamespace(
        limiter=SimpleNamespace(
            get_window_stats=lambda *_a, **_k: (reset_at - 1, 0),
        )
    )
    app = SimpleNamespace(state=SimpleNamespace(limiter=limiter))
    request = _request(app=app)
    request.state.view_rate_limit = (MagicMock(), ["key"])
    retry = _retry_after_seconds(request, MagicMock())
    assert 15 <= retry <= 18
