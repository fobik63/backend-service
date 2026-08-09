"""Async Redis distributed locks with mandatory TTL (race-condition guard).

Use for short critical sections that cannot rely solely on Postgres row locks
(cross-process coordination, Celery fan-out, etc.). Wallet debits still use
``SELECT … FOR UPDATE`` / atomic SQL as the source of truth.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.exceptions import RedisError

from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

# Lua: release only if we still own the token (avoid deleting another holder's lock).
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RedisLockError(RuntimeError):
    """Raised when a lock cannot be acquired within the wait budget."""


class RedisDistributedLock:
    """SET NX EX lock with safe compare-and-delete release."""

    def __init__(
        self,
        key: str,
        *,
        ttl_seconds: int = 30,
        token: str | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive.")
        cleaned = (key or "").strip()
        if not cleaned:
            raise ValueError("lock key must be non-empty.")
        self._key = cleaned if cleaned.startswith("lock:") else f"lock:{cleaned}"
        self._ttl = int(ttl_seconds)
        self._token = token or uuid.uuid4().hex
        self._held = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def token(self) -> str:
        return self._token

    async def acquire(self, *, blocking: bool = False, wait_seconds: float = 0.0) -> bool:
        """Try to acquire the lock. Optionally spin until ``wait_seconds`` elapses."""

        import asyncio

        deadline = asyncio.get_running_loop().time() + max(0.0, wait_seconds)
        while True:
            try:
                created = await get_redis_client().set(
                    self._key,
                    self._token,
                    nx=True,
                    ex=self._ttl,
                )
            except RedisError:
                logger.warning("Redis lock acquire failed key=%s", self._key, exc_info=True)
                return False
            if created:
                self._held = True
                return True
            if not blocking:
                return False
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def release(self) -> bool:
        """Release if this instance still owns the lock. Always clears local held flag."""

        if not self._held:
            return False
        self._held = False
        try:
            result = await get_redis_client().eval(_RELEASE_LUA, 1, self._key, self._token)
            return int(result or 0) == 1
        except RedisError:
            logger.warning("Redis lock release failed key=%s", self._key, exc_info=True)
            return False

    async def extend(self, ttl_seconds: int | None = None) -> bool:
        """Refresh TTL while still holding the lock (long critical sections)."""

        if not self._held:
            return False
        ttl = int(ttl_seconds) if ttl_seconds is not None else self._ttl
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive.")
        try:
            current = await get_redis_client().get(self._key)
            if current != self._token:
                self._held = False
                return False
            return bool(await get_redis_client().expire(self._key, ttl))
        except RedisError:
            logger.warning("Redis lock extend failed key=%s", self._key, exc_info=True)
            return False


@asynccontextmanager
async def redis_lock(
    key: str,
    *,
    ttl_seconds: int = 30,
    blocking: bool = True,
    wait_seconds: float = 5.0,
    raise_on_fail: bool = True,
) -> AsyncIterator[RedisDistributedLock]:
    """Context manager that acquires a Redis lock and always attempts release."""

    lock = RedisDistributedLock(key, ttl_seconds=ttl_seconds)
    acquired = await lock.acquire(blocking=blocking, wait_seconds=wait_seconds)
    if not acquired:
        if raise_on_fail:
            raise RedisLockError(f"Could not acquire Redis lock: {lock.key}")
        yield lock
        return
    try:
        yield lock
    finally:
        await lock.release()


__all__ = [
    "RedisDistributedLock",
    "RedisLockError",
    "redis_lock",
]
