"""Redis adapter for popular style presets with local fail-open behaviour."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from pydantic import ValidationError
from redis.exceptions import RedisError

from app.config.style_presets import (
    NicheStylePreset,
    get_niche_preset,
    resolve_niche_key,
    style_preset_content_version,
)
from app.core.config import get_settings
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
    get_redis_client,
)

logger = logging.getLogger(__name__)


class RedisStylePresetCache:
    """Cache adapter; Redis loss never prevents style generation."""

    async def get_niche(self, product_category: str | None) -> dict[str, Any] | None:
        niche_key = resolve_niche_key(product_category)
        if niche_key is None:
            return None
        settings = get_settings()
        cache_key = (
            f"style:preset:{settings.style_cache_version}:"
            f"{style_preset_content_version()}:{niche_key}"
        )
        try:
            cached = await get_cached_json(cache_key)
            if cached is not None:
                validated = NicheStylePreset.model_validate(cached)
                await self._increment_usage(niche_key)
                return validated.model_dump(mode="python")
        except (RedisUnavailableError, ValidationError):
            logger.debug("Style cache read failed for %s", niche_key, exc_info=True)

        local = get_niche_preset(niche_key)
        if local is None:
            return None
        validated = NicheStylePreset.model_validate(local)
        payload = validated.model_dump(mode="json")
        try:
            await cache_json(
                cache_key,
                payload,
                ttl_seconds=settings.style_cache_ttl_seconds,
            )
            await self._increment_usage(niche_key)
        except RedisUnavailableError:
            logger.debug("Style cache write failed for %s", niche_key, exc_info=True)
        return validated.model_dump(mode="python")

    async def _increment_usage(self, niche_key: str) -> None:
        try:
            settings = get_settings()
            client = get_redis_client()
            key = f"style:usage:{niche_key}"
            await client.incr(key)
            await client.expire(key, settings.style_cache_ttl_seconds)
        except RedisError:
            logger.debug("Style usage counter failed for %s", niche_key)


@lru_cache(maxsize=1)
def get_style_cache() -> RedisStylePresetCache:
    return RedisStylePresetCache()
