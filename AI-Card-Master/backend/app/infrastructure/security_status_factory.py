"""Factory wiring for Security & Status (plan §62)."""

from __future__ import annotations

from functools import lru_cache

from app.application.security_status_service import SecurityStatusService
from app.core.config import Settings, get_settings
from app.domain.security_status import BlockedThreatEvent
from app.infrastructure.security.api_balance_probes import HttpApiBalanceProbes
from app.infrastructure.security.rate_limiter import (
    RedisRpsMeter,
    append_blocked_threat,
    list_blocked_threats,
)
from app.infrastructure.security.system_metrics import PsutilHostMetrics


class RedisBlockedThreatLog:
    """``BlockedThreatLogPort`` over Redis JSON ring buffer."""

    async def append(self, event: BlockedThreatEvent) -> None:
        await append_blocked_threat(
            ip=event.ip,
            category=event.category,
            path=event.path,
            action=event.action,
            http_status=event.http_status,
            score=event.score,
            api_key_fingerprint=event.api_key_fingerprint,
        )

    async def list_recent(self, *, limit: int = 50) -> list[BlockedThreatEvent]:
        return await list_blocked_threats(limit=limit)


@lru_cache(maxsize=1)
def get_security_status_service() -> SecurityStatusService:
    """Process-scoped service (balance probe cache lives here)."""

    settings = get_settings()
    return build_security_status_service(settings)


def build_security_status_service(
    settings: Settings | None = None,
) -> SecurityStatusService:
    cfg = settings or get_settings()
    return SecurityStatusService(
        host_metrics=PsutilHostMetrics(),
        rps_meter=RedisRpsMeter(),
        threat_log=RedisBlockedThreatLog(),
        api_probes=HttpApiBalanceProbes(cfg),
        rps_window_seconds=cfg.security_status_rps_window_seconds,
        balance_cache_seconds=cfg.security_status_api_balance_cache_seconds,
    )
