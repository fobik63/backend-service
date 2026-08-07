"""Redis SET NX EX cooldown for cost-budget alerts (audit R2)."""

from __future__ import annotations

import logging

from redis.exceptions import RedisError

from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)


class RedisCostAlertCooldown:
    """Distributed once-per-window claim; fail-open when Redis is down."""

    async def claim(self, *, kind: str, ttl_seconds: float) -> bool:
        key_kind = (kind or "unknown").strip()[:64] or "unknown"
        ttl = int(max(1, ttl_seconds))
        try:
            created = await get_redis_client().set(
                f"cost:alert:{key_kind}",
                "1",
                nx=True,
                ex=ttl,
            )
            return bool(created)
        except RedisError:
            logger.warning(
                "Redis unavailable for cost-alert cooldown kind=%s",
                key_kind,
                exc_info=True,
            )
            return True


class NoopCostAlertCooldown:
    """Always allows alerts (tests / cooldown disabled)."""

    async def claim(self, *, kind: str, ttl_seconds: float) -> bool:
        _ = kind, ttl_seconds
        return True
