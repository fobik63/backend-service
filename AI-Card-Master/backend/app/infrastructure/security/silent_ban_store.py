"""Redis adapter for silently flagged client IPs."""

from __future__ import annotations

import logging

from redis.exceptions import RedisError

from app.application.ports.silent_ban import SilentBanStoreUnavailableError
from app.infrastructure.redis import get_security_redis_client

logger = logging.getLogger(__name__)


class RedisSilentBanStore:
    """Marks and looks up flagged client IPs for silent rate limiting."""

    def __init__(self, *, key_prefix: str = "security:silent_ban") -> None:
        self._prefix = key_prefix.rstrip(":")

    def _ip_key(self, ip: str) -> str:
        return f"{self._prefix}:ip:{ip.strip()}"

    async def mark_flagged_ip(self, *, ip: str, ttl_seconds: int) -> None:
        value = (ip or "").strip()
        if not value or value.lower() in {"unknown", "localhost"}:
            return
        try:
            client = get_security_redis_client()
            key = self._ip_key(value)
            if ttl_seconds > 0:
                await client.set(key, "1", ex=ttl_seconds)
            else:
                await client.set(key, "1")
        except RedisError as exc:
            logger.warning(
                "Redis unavailable while marking flagged IP; continuing with DB flag only",
                exc_info=True,
            )
            raise SilentBanStoreUnavailableError(
                "Silent-ban IP store unavailable."
            ) from exc

    async def is_flagged_ip(self, *, ip: str) -> bool:
        value = (ip or "").strip()
        if not value or value.lower() in {"unknown", "localhost"}:
            return False
        try:
            raw = await get_security_redis_client().get(self._ip_key(value))
            return bool(raw)
        except RedisError:
            # Fail-open: do not clamp the whole fleet to 1/5min if Redis is down.
            logger.warning(
                "Redis unavailable for silent-ban IP lookup; fail-open",
                exc_info=True,
            )
            return False
