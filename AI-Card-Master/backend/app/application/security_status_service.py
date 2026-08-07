"""Application service: Security & Status snapshot assembly (plan §62)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from app.application.ports.security_status import (
    ApiBalanceProbePort,
    BlockedThreatLogPort,
    HostMetricsPort,
    RpsMeterPort,
)
from app.domain.security_status import ApiBalanceStatus, SecurityStatusSnapshot


class SecurityStatusService:
    """Collect host metrics, RPS, provider balances, and blocked-threat log."""

    def __init__(
        self,
        *,
        host_metrics: HostMetricsPort,
        rps_meter: RpsMeterPort,
        threat_log: BlockedThreatLogPort,
        api_probes: ApiBalanceProbePort,
        rps_window_seconds: int = 5,
        balance_cache_seconds: float = 60.0,
    ) -> None:
        self._host_metrics = host_metrics
        self._rps_meter = rps_meter
        self._threat_log = threat_log
        self._api_probes = api_probes
        self._rps_window_seconds = max(1, rps_window_seconds)
        self._balance_cache_seconds = max(0.0, balance_cache_seconds)
        self._mj_cache: tuple[float, ApiBalanceStatus] | None = None
        self._claude_cache: tuple[float, ApiBalanceStatus] | None = None

    async def get_snapshot(self, *, threats_limit: int = 50) -> SecurityStatusSnapshot:
        host, rps, threats, midjourney, claude = await asyncio.gather(
            self._host_metrics.sample(),
            self._rps_meter.current_rps(window_seconds=self._rps_window_seconds),
            self._threat_log.list_recent(limit=threats_limit),
            self._cached_midjourney(),
            self._cached_claude(),
        )
        return SecurityStatusSnapshot(
            collected_at=datetime.now(UTC),
            cpu_percent=host.cpu_percent,
            ram_percent=host.ram_percent,
            ram_used_mb=host.ram_used_mb,
            ram_total_mb=host.ram_total_mb,
            rps=rps.rps,
            rps_window_seconds=rps.window_seconds,
            midjourney=midjourney,
            claude=claude,
            blocked_threats=tuple(threats),
            blocked_threats_count=len(threats),
        )

    async def _cached_midjourney(self) -> ApiBalanceStatus:
        cached = self._mj_cache
        now = time.monotonic()
        if (
            cached is not None
            and self._balance_cache_seconds > 0
            and (now - cached[0]) < self._balance_cache_seconds
        ):
            return cached[1]
        status = await self._api_probes.probe_midjourney()
        self._mj_cache = (now, status)
        return status

    async def _cached_claude(self) -> ApiBalanceStatus:
        cached = self._claude_cache
        now = time.monotonic()
        if (
            cached is not None
            and self._balance_cache_seconds > 0
            and (now - cached[0]) < self._balance_cache_seconds
        ):
            return cached[1]
        status = await self._api_probes.probe_claude()
        self._claude_cache = (now, status)
        return status
