"""Redis hot-cache for personal cabinet generation history (plan §16)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    delete_keys_by_prefix,
    get_cached_json,
)

logger = logging.getLogger(__name__)

_HISTORY_PREFIX = "generation:history:"
_TARIFFS_KEY = "static:tariffs:v1"


def history_cache_key(*, user_id: UUID, limit: int, offset: int) -> str:
    return f"{_HISTORY_PREFIX}{user_id}:{limit}:{offset}"


async def get_cached_generation_history(
    *,
    user_id: UUID,
    limit: int,
    offset: int,
) -> list[dict[str, Any]] | None:
    """Return cached history items or None on miss / Redis failure."""

    try:
        payload = await get_cached_json(
            history_cache_key(user_id=user_id, limit=limit, offset=offset)
        )
    except RedisUnavailableError:
        logger.debug("Generation history cache read failed", exc_info=True)
        return None
    if payload is None:
        return None
    items = payload.get("items")
    return items if isinstance(items, list) else None


async def set_cached_generation_history(
    *,
    user_id: UUID,
    limit: int,
    offset: int,
    items: list[dict[str, Any]],
) -> None:
    """Store history JSON under a short TTL (presigned URLs expire)."""

    settings = get_settings()
    try:
        await cache_json(
            history_cache_key(user_id=user_id, limit=limit, offset=offset),
            {"items": items},
            ttl_seconds=settings.generation_history_cache_ttl_seconds,
        )
    except RedisUnavailableError:
        logger.debug("Generation history cache write failed", exc_info=True)


async def invalidate_generation_history_cache(user_id: UUID) -> None:
    """Drop all paginated history pages for a user after create/finalize."""

    try:
        await delete_keys_by_prefix(f"{_HISTORY_PREFIX}{user_id}:")
    except RedisUnavailableError:
        logger.debug(
            "Generation history cache invalidate failed for %s",
            user_id,
            exc_info=True,
        )


async def get_cached_tariffs() -> list[dict[str, Any]] | None:
    """Return cached public tariff catalog."""

    try:
        payload = await get_cached_json(_TARIFFS_KEY)
    except RedisUnavailableError:
        logger.debug("Tariffs cache read failed", exc_info=True)
        return None
    if payload is None:
        return None
    items = payload.get("items")
    return items if isinstance(items, list) else None


async def set_cached_tariffs(items: list[dict[str, Any]]) -> None:
    """Cache static tariff grid (long TTL; catalog rarely changes)."""

    settings = get_settings()
    try:
        await cache_json(
            _TARIFFS_KEY,
            {"items": items},
            ttl_seconds=settings.static_cache_ttl_seconds,
        )
    except RedisUnavailableError:
        logger.debug("Tariffs cache write failed", exc_info=True)
