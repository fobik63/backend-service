"""Redis-backed request rate limiting and temporary IP blocks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0
    reason: str | None = None


async def is_ip_blocked(ip: str) -> bool:
    """Return True when the IP has an active temporary block."""

    try:
        return bool(await get_redis_client().exists(f"security:ip_block:{ip}"))
    except RedisError:
        logger.warning("Redis unavailable for IP block lookup", exc_info=True)
        return False


async def block_ip(ip: str, *, ttl_seconds: int, reason: str) -> None:
    """Temporarily block an IP address."""

    if ttl_seconds <= 0:
        return
    try:
        await get_redis_client().set(
            f"security:ip_block:{ip}",
            reason[:200],
            ex=ttl_seconds,
        )
    except RedisError:
        logger.warning("Redis unavailable for IP block write", exc_info=True)


async def record_threat_event(ip: str, *, category: str, path: str) -> int:
    """Increment threat score for an IP; return the new score."""

    key = f"security:threat_score:{ip}"
    try:
        client = get_redis_client()
        score = int(await client.incr(key))
        await client.expire(key, 3600)
        await client.lpush(
            f"security:threat_log:{ip}",
            f"{category}:{path[:120]}",
        )
        await client.ltrim(f"security:threat_log:{ip}", 0, 49)
        await client.expire(f"security:threat_log:{ip}", 86400)
        return score
    except RedisError:
        logger.warning("Redis unavailable for threat scoring", exc_info=True)
        return 0


async def check_rate_limit(
    *,
    ip: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Sliding fixed-window counter per IP. Fail-open if Redis is down."""

    if limit <= 0 or window_seconds <= 0:
        return RateLimitDecision(allowed=True, remaining=0)

    key = f"security:rate:{ip}:{window_seconds}"
    try:
        client = get_redis_client()
        count = int(await client.incr(key))
        if count == 1:
            await client.expire(key, window_seconds)
        ttl = int(await client.ttl(key))
        remaining = max(limit - count, 0)
        if count > limit:
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                retry_after_seconds=max(ttl, 1),
                reason="rate_limit",
            )
        return RateLimitDecision(allowed=True, remaining=remaining)
    except RedisError:
        logger.warning("Redis unavailable for rate limiting; allowing request")
        return RateLimitDecision(allowed=True, remaining=limit)
