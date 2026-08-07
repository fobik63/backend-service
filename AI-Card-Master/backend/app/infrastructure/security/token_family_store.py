"""Redis adapter for Refresh Token Rotation (RTR) / Token Families."""

from __future__ import annotations

import logging
from typing import Any

from redis.exceptions import RedisError

from app.application.ports.token_family import TokenFamilyStoreUnavailableError
from app.infrastructure.redis import get_security_redis_client

logger = logging.getLogger(__name__)


class RedisTokenFamilyStore:
    """JTI blacklist + family burn flags on the security Redis instance."""

    def __init__(
        self,
        *,
        key_prefix: str = "auth:rtr",
        client: Any | None = None,
    ) -> None:
        self._prefix = key_prefix.rstrip(":")
        self._client = client

    def _redis(self) -> Any:
        return self._client if self._client is not None else get_security_redis_client()

    def _jti_key(self, jti: str) -> str:
        return f"{self._prefix}:jti:{jti.strip()}"

    def _family_key(self, family_id: str) -> str:
        return f"{self._prefix}:family:{family_id.strip()}"

    async def blacklist_jti_if_new(self, *, jti: str, ttl_seconds: int) -> bool:
        value = (jti or "").strip()
        if not value:
            raise ValueError("jti must be a non-empty string.")
        ttl = max(1, int(ttl_seconds))
        try:
            created = await self._redis().set(
                self._jti_key(value),
                "1",
                nx=True,
                ex=ttl,
            )
            return bool(created)
        except RedisError as exc:
            logger.warning("Redis unavailable while blacklisting refresh jti", exc_info=True)
            raise TokenFamilyStoreUnavailableError(
                "Token family store unavailable."
            ) from exc

    async def is_jti_blacklisted(self, *, jti: str) -> bool:
        value = (jti or "").strip()
        if not value:
            return False
        try:
            return bool(await self._redis().exists(self._jti_key(value)))
        except RedisError as exc:
            logger.warning("Redis unavailable for refresh jti lookup", exc_info=True)
            raise TokenFamilyStoreUnavailableError(
                "Token family store unavailable."
            ) from exc

    async def is_family_burned(self, *, family_id: str) -> bool:
        value = (family_id or "").strip()
        if not value:
            return False
        try:
            return bool(await self._redis().exists(self._family_key(value)))
        except RedisError as exc:
            logger.warning("Redis unavailable for family burn lookup", exc_info=True)
            raise TokenFamilyStoreUnavailableError(
                "Token family store unavailable."
            ) from exc

    async def burn_family(self, *, family_id: str, ttl_seconds: int) -> None:
        value = (family_id or "").strip()
        if not value:
            raise ValueError("family_id must be a non-empty string.")
        ttl = max(1, int(ttl_seconds))
        try:
            await self._redis().set(
                self._family_key(value),
                "burned",
                ex=ttl,
            )
        except RedisError as exc:
            logger.warning("Redis unavailable while burning token family", exc_info=True)
            raise TokenFamilyStoreUnavailableError(
                "Token family store unavailable."
            ) from exc
