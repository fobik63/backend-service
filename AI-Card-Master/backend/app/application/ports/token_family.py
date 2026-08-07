"""Port: Refresh Token Rotation (RTR) blacklist + token-family burn store."""

from __future__ import annotations

from typing import Protocol


class TokenFamilyStoreUnavailableError(RuntimeError):
    """Security Redis is unreachable for RTR operations."""


class TokenFamilyStorePort(Protocol):
    """Durable Redis-backed state for refresh-token reuse detection."""

    async def blacklist_jti_if_new(self, *, jti: str, ttl_seconds: int) -> bool:
        """Atomically blacklist ``jti``.

        Returns:
            True if this was the first use (key created).
            False if ``jti`` was already blacklisted (reuse).
        """

        ...

    async def is_jti_blacklisted(self, *, jti: str) -> bool:
        """Return whether a refresh ``jti`` has already been consumed."""

        ...

    async def is_family_burned(self, *, family_id: str) -> bool:
        """Return whether the token family has been revoked (FAMILY BURN)."""

        ...

    async def burn_family(self, *, family_id: str, ttl_seconds: int) -> None:
        """Revoke an entire refresh-token family chain."""

        ...
