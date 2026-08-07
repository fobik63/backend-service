"""Redis adapter for signup trial fingerprint + /24 subnet counters."""

from __future__ import annotations

import logging
from typing import NoReturn

from redis.exceptions import RedisError

from app.application.ports.signup_trial import SignupTrialStoreUnavailableError
from app.infrastructure.redis import get_security_redis_client

logger = logging.getLogger(__name__)

_FP_SEEN = "seen"
_FP_EXHAUSTED = "exhausted"


class RedisSignupTrialStore:
    """Security-Redis keys for device fingerprints and subnet rate limits."""

    def __init__(self, *, key_prefix: str = "security:signup_trial") -> None:
        self._prefix = key_prefix.rstrip(":")

    def _fp_key(self, fingerprint_hash: str) -> str:
        return f"{self._prefix}:fp:{fingerprint_hash}"

    def _subnet_key(self, subnet: str) -> str:
        return f"{self._prefix}:subnet:{subnet}"

    def _raise_unavailable(self, operation: str) -> NoReturn:
        logger.warning(
            "Redis unavailable for signup trial %s; fail-closed",
            operation,
            exc_info=True,
        )
        raise SignupTrialStoreUnavailableError(
            f"Signup trial security store unavailable during {operation}."
        )

    async def is_fingerprint_exhausted(self, *, fingerprint_hash: str) -> bool:
        try:
            value = await get_security_redis_client().get(self._fp_key(fingerprint_hash))
            return value == _FP_EXHAUSTED
        except RedisError:
            self._raise_unavailable("fingerprint lookup")

    async def remember_fingerprint(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        """Persist the hash in Redis without marking the trial as consumed."""

        try:
            client = get_security_redis_client()
            key = self._fp_key(fingerprint_hash)
            # Do not downgrade an already exhausted fingerprint back to "seen".
            current = await client.get(key)
            if current == _FP_EXHAUSTED:
                return
            if ttl_seconds > 0:
                await client.set(key, _FP_SEEN, ex=ttl_seconds)
            else:
                await client.set(key, _FP_SEEN)
        except RedisError:
            self._raise_unavailable("fingerprint remember")

    async def mark_fingerprint_exhausted(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        try:
            client = get_security_redis_client()
            if ttl_seconds > 0:
                await client.set(
                    self._fp_key(fingerprint_hash),
                    _FP_EXHAUSTED,
                    ex=ttl_seconds,
                )
            else:
                await client.set(self._fp_key(fingerprint_hash), _FP_EXHAUSTED)
        except RedisError:
            self._raise_unavailable("fingerprint mark")

    async def increment_subnet_registrations(
        self,
        *,
        subnet: str,
        ttl_seconds: int,
    ) -> int:
        key = self._subnet_key(subnet)
        try:
            client = get_security_redis_client()
            count = int(await client.incr(key))
            if count == 1 and ttl_seconds > 0:
                await client.expire(key, ttl_seconds)
            return count
        except RedisError:
            self._raise_unavailable("subnet counter")
