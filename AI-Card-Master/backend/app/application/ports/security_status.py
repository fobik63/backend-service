"""Ports for admin Security & Status (plan §62)."""

from __future__ import annotations

from typing import Protocol

from app.domain.security_status import (
    ApiBalanceStatus,
    BlockedThreatEvent,
    HostResourceMetrics,
    RequestsPerSecondMetrics,
    SecurityStatusSnapshot,
)


class HostMetricsPort(Protocol):
    async def sample(self) -> HostResourceMetrics:
        """Non-blocking CPU / RAM sample."""


class RpsMeterPort(Protocol):
    async def record_request(self) -> None:
        """Increment the current second bucket."""

    async def current_rps(self, *, window_seconds: int) -> RequestsPerSecondMetrics:
        """Estimate RPS over the last ``window_seconds``."""


class BlockedThreatLogPort(Protocol):
    async def append(self, event: BlockedThreatEvent) -> None:
        """Push a blocked threat into the ring buffer (max 50)."""

    async def list_recent(self, *, limit: int = 50) -> list[BlockedThreatEvent]:
        """Newest-first blocked threats."""


class ApiBalanceProbePort(Protocol):
    async def probe_midjourney(self) -> ApiBalanceStatus:
        """Check Midjourney provider balance / reachability."""

    async def probe_claude(self) -> ApiBalanceStatus:
        """Check Claude / Anthropic API balance / reachability."""


class SecurityStatusServicePort(Protocol):
    async def get_snapshot(self, *, threats_limit: int = 50) -> SecurityStatusSnapshot:
        """Collect a full live status snapshot."""
