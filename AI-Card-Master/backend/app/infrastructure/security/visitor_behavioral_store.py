"""Redis adapter for visitor generation counters and CAPTCHA blocks.

Generation enqueue is a fail-closed security path: RedisError raises
``RedisUnavailableError`` so callers can return HTTP 503 + Retry-After.
"""

from __future__ import annotations

import logging
from typing import NoReturn

from redis.exceptions import RedisError

from app.infrastructure.redis import RedisUnavailableError, get_security_redis_client

logger = logging.getLogger(__name__)


class RedisVisitorBehavioralStore:
    """Persist per-visitor generation frequency and CAPTCHA challenge state."""

    def __init__(self, *, key_prefix: str = "security:behavioral") -> None:
        self._prefix = key_prefix.rstrip(":")

    def _rate_key(self, subject_key: str, window_seconds: int) -> str:
        return f"{self._prefix}:rate:{subject_key}:{window_seconds}"

    def _block_key(self, subject_key: str) -> str:
        return f"{self._prefix}:captcha_block:{subject_key}"

    def _raise_unavailable(self, operation: str) -> NoReturn:
        logger.warning(
            "Redis unavailable for behavioral %s; fail-closed",
            operation,
            exc_info=True,
        )
        raise RedisUnavailableError(
            f"Behavioral security store unavailable during {operation}."
        )

    async def is_captcha_blocked(self, *, subject_key: str) -> bool:
        try:
            return bool(await get_security_redis_client().exists(self._block_key(subject_key)))
        except RedisError:
            self._raise_unavailable("CAPTCHA block lookup")

    async def get_captcha_block_ttl(self, *, subject_key: str) -> int:
        try:
            ttl = int(await get_security_redis_client().ttl(self._block_key(subject_key)))
            return max(ttl, 0)
        except RedisError:
            self._raise_unavailable("CAPTCHA block TTL")

    async def increment_generation_counter(
        self,
        *,
        subject_key: str,
        window_seconds: int,
    ) -> int:
        key = self._rate_key(subject_key, window_seconds)
        try:
            client = get_security_redis_client()
            count = int(await client.incr(key))
            if count == 1:
                await client.expire(key, window_seconds)
            return count
        except RedisError:
            self._raise_unavailable("generation counter")

    async def set_captcha_block(self, *, subject_key: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            await get_security_redis_client().set(
                self._block_key(subject_key),
                "CAPTCHA_REQUIRED",
                ex=ttl_seconds,
            )
        except RedisError:
            self._raise_unavailable("CAPTCHA block write")

    async def clear_captcha_block(
        self,
        *,
        subject_key: str,
        window_seconds: int,
    ) -> None:
        try:
            client = get_security_redis_client()
            await client.delete(self._block_key(subject_key))
            await client.delete(self._rate_key(subject_key, window_seconds))
        except RedisError:
            self._raise_unavailable("CAPTCHA block clear")
