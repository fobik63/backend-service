"""Redis-backed optional cache for Claude intermediate stage payloads."""

from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.redis import RedisUnavailableError, cache_json, get_cached_json

logger = logging.getLogger(__name__)


class RedisClaudeStageCache:
    """Fail-open stage cache; Redis outages never fail analysis."""

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            return await get_cached_json(key)
        except RedisUnavailableError:
            logger.warning("Redis unavailable; Claude stage cache miss key=%s", key)
            return None

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        try:
            await cache_json(key, payload, ttl_seconds)
        except RedisUnavailableError:
            logger.warning("Redis unavailable; skipped Claude stage cache key=%s", key)
