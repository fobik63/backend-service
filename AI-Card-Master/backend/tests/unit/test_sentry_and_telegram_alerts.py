"""Unit tests for Sentry PII scrubbing and short Telegram 500 alerts."""

from __future__ import annotations

from uuid import uuid4

from starlette.requests import Request

from app.infrastructure.observability.sentry import (
    before_send,
    scrub_sensitive_data,
    scrub_sensitive_string,
)
from app.services.telegram_alerts import (
    _format_http_alert,
    extract_error_location,
    resolve_request_user_id,
)


def test_scrub_sensitive_data_masks_password_and_api_key_fields() -> None:
    payload = {
        "username": "alice",
        "password": "super-secret",
        "nested": {"api_key": "sk-live-abc123456789", "ok": True},
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb",
    }
    scrubbed = scrub_sensitive_data(payload)
    assert scrubbed["username"] == "alice"
    assert scrubbed["password"] == "[Filtered]"
    assert scrubbed["nested"]["api_key"] == "[Filtered]"
    assert scrubbed["nested"]["ok"] is True
    assert scrubbed["Authorization"] == "[Filtered]"


def test_scrub_sensitive_string_masks_jwt_and_api_key_shapes() -> None:
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
    text = f"token={jwt} key=sk-test-ABCDEFGH12345678"
    scrubbed = scrub_sensitive_string(text)
    assert jwt not in scrubbed
    assert "sk-test-ABCDEFGH12345678" not in scrubbed
    assert "[Filtered]" in scrubbed


def test_before_send_strips_request_pii_and_user_email() -> None:
    event = {
        "request": {
            "headers": {
                "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.a.b",
                "content-type": "application/json",
            },
            "data": {"password": "x", "email": "a@b.c"},
        },
        "user": {"id": "u-1", "email": "a@b.c", "ip_address": "1.2.3.4"},
        "message": "failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.a.b",
    }
    result = before_send(event, {})
    assert result is not None
    assert result["request"]["headers"]["authorization"] == "[Filtered]"
    assert result["request"]["headers"]["content-type"] == "application/json"
    assert result["request"]["data"]["password"] == "[Filtered]"
    assert result["user"] == {"id": "u-1"}
    assert "eyJ" not in result["message"]


def _make_request(*, path: str = "/api/v1/demo", method: str = "POST", user_id: str | None = None) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    if user_id is not None:
        request.state.user_id = user_id
    return request


def test_format_http_alert_is_short_and_includes_required_fields() -> None:
    user_id = str(uuid4())

    def _boom() -> None:
        raise RuntimeError("db connection lost")

    try:
        _boom()
    except RuntimeError as exc:
        message = _format_http_alert(_make_request(user_id=user_id), exc)

    assert "AI-Card-Master 500" in message
    assert "file:" in message
    assert "line:" in message
    assert "endpoint: POST /api/v1/demo" in message
    assert f"user_id: {user_id}" in message
    assert "RuntimeError: db connection lost" in message
    assert "Traceback" not in message


def test_resolve_request_user_id_from_state() -> None:
    user_id = str(uuid4())
    assert resolve_request_user_id(_make_request(user_id=user_id)) == user_id
    assert resolve_request_user_id(_make_request()) is None


def test_extract_error_location_prefers_app_frame() -> None:
    try:
        raise ValueError("x")
    except ValueError as exc:
        location = extract_error_location(exc)
    assert location.lineno > 0
    assert location.func_name
