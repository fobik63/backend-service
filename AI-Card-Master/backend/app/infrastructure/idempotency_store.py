"""Redis-backed idempotency state for charge / generation mutations."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from redis.exceptions import RedisError

from app.infrastructure.redis import RedisUnavailableError, get_redis_client

logger = logging.getLogger(__name__)

IdempotencyStatus = Literal["PROCESSING", "COMPLETED"]

STATUS_PROCESSING: IdempotencyStatus = "PROCESSING"
STATUS_COMPLETED: IdempotencyStatus = "COMPLETED"

_KEY_PREFIX = "idempotency:v1:"


def redis_idempotency_key(scope: str, idempotency_key: str) -> str:
    """Build a namespaced Redis key for an idempotency scope + client key."""

    return f"{_KEY_PREFIX}{scope}:{idempotency_key}"


async def claim_processing(*, scope: str, idempotency_key: str, ttl_seconds: int) -> bool:
    """Atomically claim PROCESSING. Returns True when this request owns the key."""

    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive.")
    key = redis_idempotency_key(scope, idempotency_key)
    payload = json.dumps(
        {"status": STATUS_PROCESSING},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        created = await get_redis_client().set(key, payload, nx=True, ex=ttl_seconds)
        return bool(created)
    except RedisError as exc:
        raise RedisUnavailableError("Idempotency claim failed.") from exc


async def get_idempotency_record(
    *, scope: str, idempotency_key: str
) -> dict[str, Any] | None:
    """Return the stored idempotency record, or None when missing."""

    key = redis_idempotency_key(scope, idempotency_key)
    try:
        raw = await get_redis_client().get(key)
    except RedisError as exc:
        raise RedisUnavailableError("Idempotency read failed.") from exc
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        try:
            await get_redis_client().delete(key)
        except RedisError:
            logger.warning("Could not delete corrupt idempotency key %s", key)
        raise RedisUnavailableError("Idempotency value is invalid.") from exc
    return parsed if isinstance(parsed, dict) else None


async def store_completed_response(
    *,
    scope: str,
    idempotency_key: str,
    status_code: int,
    body: str,
    media_type: str | None,
    ttl_seconds: int,
) -> None:
    """Persist a successful response for replay within the completion TTL."""

    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive.")
    key = redis_idempotency_key(scope, idempotency_key)
    payload = json.dumps(
        {
            "status": STATUS_COMPLETED,
            "status_code": int(status_code),
            "body": body,
            "media_type": media_type or "application/json",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        await get_redis_client().set(key, payload, ex=ttl_seconds)
    except RedisError as exc:
        raise RedisUnavailableError("Idempotency complete write failed.") from exc


async def release_processing(*, scope: str, idempotency_key: str) -> None:
    """Drop a PROCESSING marker so the client may safely retry after failure."""

    key = redis_idempotency_key(scope, idempotency_key)
    try:
        record = await get_idempotency_record(scope=scope, idempotency_key=idempotency_key)
        if record is None:
            return
        if record.get("status") != STATUS_PROCESSING:
            return
        await get_redis_client().delete(key)
    except RedisUnavailableError:
        raise
    except RedisError as exc:
        raise RedisUnavailableError("Idempotency release failed.") from exc
