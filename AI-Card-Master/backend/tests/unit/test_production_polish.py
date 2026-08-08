"""Unit tests for Redis distributed locks and JSON logging helpers."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from app.core.http_errors import shape_error_envelope, shape_http_exception_body
from app.core.logging_config import JsonLogFormatter, RequestIdLogFilter
from app.core.request_context import (
    RequestAuditContext,
    reset_request_audit_context,
    set_request_audit_context,
)
from app.infrastructure.redis_lock import RedisDistributedLock, RedisLockError, redis_lock
from starlette.exceptions import HTTPException


@pytest.mark.asyncio
async def test_redis_lock_acquire_release(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.set = AsyncMock(return_value=True)
    client.eval = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.get_redis_client",
        lambda: client,
    )

    lock = RedisDistributedLock("wallet:user-1", ttl_seconds=10)
    assert await lock.acquire() is True
    assert lock.key == "lock:wallet:user-1"
    client.set.assert_awaited()
    assert await lock.release() is True
    client.eval.assert_awaited()


@pytest.mark.asyncio
async def test_redis_lock_context_raises_when_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.set = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.get_redis_client",
        lambda: client,
    )

    with pytest.raises(RedisLockError):
        async with redis_lock("busy", ttl_seconds=5, blocking=False, wait_seconds=0):
            pass


def test_json_log_formatter_includes_request_id() -> None:
    token = set_request_audit_context(
        RequestAuditContext(request_id="req-abc-123")
    )
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert RequestIdLogFilter().filter(record) is True
        payload = json.loads(JsonLogFormatter().format(record))
        assert payload["message"] == "hello"
        assert payload["request_id"] == "req-abc-123"
        assert payload["correlation_id"] == "req-abc-123"
        assert payload["level"] == "INFO"
    finally:
        reset_request_audit_context(token)


def test_shape_http_exception_includes_nested_error() -> None:
    exc = HTTPException(status_code=400, detail="Bad input")
    body = shape_http_exception_body(exc)
    assert body["success"] is False
    assert body["detail"] == "Bad input"
    assert body["error"] == {"code": "http_400", "message": "Bad input"}


def test_shape_error_envelope_helper() -> None:
    assert shape_error_envelope(code="x", message="y") == {
        "error": {"code": "x", "message": "y"}
    }
