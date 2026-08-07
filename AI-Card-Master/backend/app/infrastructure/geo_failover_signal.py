"""Shared neural-region signal between geo failover watchdog and AI provider pool.

Cloudflare origin failover (deploy/failover_watchdog.py) and Midjourney region
ordering (ai_engine) previously used independent static Settings. This module is
the single Redis-backed bridge so a site failover also re-ranks neural providers.
"""

from __future__ import annotations

import logging
from typing import Any

from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

DEFAULT_NEURAL_ACTIVE_REGION_KEY = "geo:neural_active_region"


def neural_active_region_key(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    key = getattr(cfg, "neural_active_region_redis_key", "") or ""
    return key.strip() or DEFAULT_NEURAL_ACTIVE_REGION_KEY


async def publish_neural_active_region(
    region: str,
    *,
    settings: Settings | None = None,
) -> None:
    """Persist the active neural geo preference after infra failover/failback."""

    cleaned = region.strip().lower()
    if not cleaned:
        return
    cfg = settings or get_settings()
    try:
        await get_redis_client().set(neural_active_region_key(cfg), cleaned)
    except RedisError:
        logger.warning(
            "Failed to publish neural active region=%s", cleaned, exc_info=True
        )


async def clear_neural_active_region(*, settings: Settings | None = None) -> None:
    """Drop override so providers fall back to NEURAL_PREFERRED_REGION."""

    cfg = settings or get_settings()
    try:
        await get_redis_client().delete(neural_active_region_key(cfg))
    except RedisError:
        logger.warning("Failed to clear neural active region", exc_info=True)


async def resolve_preferred_neural_region(
    settings: Settings | None = None,
) -> str:
    """Active Redis override → static preferred region from Settings."""

    cfg = settings or get_settings()
    try:
        raw: Any = await get_redis_client().get(neural_active_region_key(cfg))
    except RedisError:
        logger.warning("Neural region signal read failed; using settings", exc_info=True)
        raw = None
    if raw:
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="ignore").strip().lower()
        else:
            text = str(raw).strip().lower()
        if text:
            return text
    return (cfg.neural_preferred_region or "").strip().lower()
