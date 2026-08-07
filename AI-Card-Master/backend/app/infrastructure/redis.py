"""Async Redis clients: expendable cache vs non-evictable security store."""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RedisUnavailableError(RuntimeError):
    """Redis operation failed; callers may fall back to PostgreSQL/local data."""


_redis_client: Redis | None = None
_security_redis_client: Redis | None = None


def _build_client(url: str) -> Redis:
    return Redis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=2,
        socket_timeout=3,
        retry_on_timeout=True,
    )


def get_redis_client() -> Redis:
    """Return the process-local lazy async Redis client (cache / broker-adjacent)."""

    global _redis_client
    if _redis_client is None:
        _redis_client = _build_client(get_settings().redis_url)
    return _redis_client


def get_security_redis_client() -> Redis:
    """Return Redis for rate limits / bans / CAPTCHA (noeviction instance in prod)."""

    global _security_redis_client
    if _security_redis_client is None:
        _security_redis_client = _build_client(
            get_settings().effective_redis_security_url
        )
    return _security_redis_client


async def close_redis_client() -> None:
    """Close the process-local cache Redis connection pool."""

    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def close_security_redis_client() -> None:
    """Close the process-local security Redis connection pool."""

    global _security_redis_client
    if _security_redis_client is not None:
        await _security_redis_client.aclose()
        _security_redis_client = None


async def redis_healthcheck() -> bool:
    """Return Redis availability without raising into a health endpoint."""

    try:
        cache_ok = bool(await get_redis_client().ping())
        security_ok = bool(await get_security_redis_client().ping())
        return cache_ok and security_ok
    except RedisError:
        logger.warning("Redis health check failed", exc_info=True)
        return False


async def cache_json(key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    """Store compact JSON with a mandatory TTL (volatile-lru safe)."""

    if ttl_seconds <= 0:
        raise ValueError("cache_json requires a positive ttl_seconds.")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        await get_redis_client().set(key, encoded, ex=ttl_seconds)
    except (RedisError, TypeError, ValueError) as exc:
        raise RedisUnavailableError("Redis JSON write failed.") from exc


async def get_cached_json(key: str) -> dict[str, Any] | None:
    """Read a cached JSON object."""

    try:
        raw = await get_redis_client().get(key)
    except RedisError as exc:
        raise RedisUnavailableError("Redis JSON read failed.") from exc
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        await get_redis_client().delete(key)
        raise RedisUnavailableError("Redis JSON value is invalid.") from exc
    return parsed if isinstance(parsed, dict) else None


async def delete_keys_by_prefix(prefix: str, *, scan_count: int = 100) -> int:
    """Best-effort SCAN+DELETE for a key prefix. Returns deleted key count."""

    deleted = 0
    try:
        client = get_redis_client()
        async for key in client.scan_iter(match=f"{prefix}*", count=scan_count):
            deleted += int(await client.delete(key))
    except RedisError as exc:
        raise RedisUnavailableError("Redis prefix delete failed.") from exc
    return deleted


async def is_provider_circuit_open(provider_name: str) -> bool:
    """Return whether a Midjourney provider circuit is OPEN (skip in pool).

    HALF_OPEN providers remain eligible so a single probe can recover health.
    """

    from app.infrastructure.circuit_breaker import get_circuit_breaker

    try:
        return await get_circuit_breaker().is_open(provider_name)
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning(
            "Circuit breaker open-check failed for %s; allowing provider",
            provider_name,
        )
        return False


async def record_provider_success(provider_name: str) -> None:
    """Reset provider failure counters after a successful operation."""

    from app.infrastructure.circuit_breaker import get_circuit_breaker

    try:
        await get_circuit_breaker().record_success(provider_name)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("Could not reset provider circuit for %s", provider_name)


async def record_provider_failure(provider_name: str) -> None:
    """Increment trip-worthy failures; open the circuit at the shared threshold."""

    from app.infrastructure.circuit_breaker import get_circuit_breaker

    try:
        await get_circuit_breaker().record_failure(provider_name, trip_worthy=True)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("Could not update provider circuit for %s", provider_name)
