"""Ports for silent-ban (flagged IP) tracking."""

from __future__ import annotations

from typing import Protocol


class SilentBanStoreUnavailableError(RuntimeError):
    """Security Redis unavailable for silent-ban IP markers."""


class SilentBanStorePort(Protocol):
    """Redis-backed set of client IPs belonging to silently flagged accounts."""

    async def mark_flagged_ip(self, *, ip: str, ttl_seconds: int) -> None:
        """Remember that this IP belongs to a silently flagged registrant."""

        ...

    async def is_flagged_ip(self, *, ip: str) -> bool:
        """Return True when the IP should receive the tight silent rate limit."""

        ...
