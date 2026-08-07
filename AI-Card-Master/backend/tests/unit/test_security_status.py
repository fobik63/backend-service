"""Unit tests for Security & Status (plan §62)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.security_status_schemas import snapshot_to_dict, snapshot_to_response
from app.application.security_status_service import SecurityStatusService
from app.domain.security_status import (
    ApiBalanceStatus,
    BlockedThreatEvent,
    HostResourceMetrics,
    RequestsPerSecondMetrics,
)
from app.infrastructure.security.rate_limiter import _parse_threat_raw


class _FakeHost:
    async def sample(self) -> HostResourceMetrics:
        return HostResourceMetrics(
            cpu_percent=12.5,
            ram_percent=44.0,
            ram_used_mb=1024.0,
            ram_total_mb=2048.0,
        )


class _FakeRps:
    async def record_request(self) -> None:
        return None

    async def current_rps(self, *, window_seconds: int) -> RequestsPerSecondMetrics:
        return RequestsPerSecondMetrics(
            rps=3.2,
            window_seconds=window_seconds,
            requests_in_window=16,
        )


class _FakeThreats:
    def __init__(self) -> None:
        self.items = [
            BlockedThreatEvent(
                id="t1",
                timestamp=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
                ip="1.2.3.4",
                category="sql_injection",
                path="/api/v1/ping",
                action="denied",
                http_status=400,
                score=1,
            )
        ]

    async def append(self, event: BlockedThreatEvent) -> None:
        self.items.insert(0, event)

    async def list_recent(self, *, limit: int = 50) -> list[BlockedThreatEvent]:
        return self.items[:limit]


class _FakeProbes:
    async def probe_midjourney(self) -> ApiBalanceStatus:
        return ApiBalanceStatus(
            provider="midjourney",
            status="ok",
            balance=42.0,
            unit="credits",
            checked_at=datetime.now(UTC),
        )

    async def probe_claude(self) -> ApiBalanceStatus:
        return ApiBalanceStatus(
            provider="claude",
            status="ok",
            message="Claude API key accepted.",
            checked_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_security_status_service_snapshot() -> None:
    service = SecurityStatusService(
        host_metrics=_FakeHost(),
        rps_meter=_FakeRps(),
        threat_log=_FakeThreats(),
        api_probes=_FakeProbes(),
        rps_window_seconds=5,
        balance_cache_seconds=60,
    )
    snap = await service.get_snapshot(threats_limit=50)
    assert snap.cpu_percent == 12.5
    assert snap.ram_percent == 44.0
    assert snap.rps == 3.2
    assert snap.midjourney.status == "ok"
    assert snap.claude.status == "ok"
    assert snap.blocked_threats_count == 1
    assert snap.blocked_threats[0].category == "sql_injection"

    payload = snapshot_to_dict(snap)
    assert payload["cpu_percent"] == 12.5
    assert payload["blocked_threats"][0]["ip"] == "1.2.3.4"
    assert snapshot_to_response(snap).blocked_threats_count == 1


def test_parse_threat_json_and_legacy() -> None:
    modern = _parse_threat_raw(
        '{"id":"abc","timestamp":"2026-08-07T01:02:03+00:00","ip":"9.9.9.9",'
        '"category":"xss","path":"/x","action":"banned","http_status":403,"score":5}'
    )
    assert modern is not None
    assert modern.ip == "9.9.9.9"
    assert modern.action == "banned"
    assert modern.score == 5

    legacy = _parse_threat_raw("10.0.0.1|rate_limit_ip|/api/v1/gen")
    assert legacy is not None
    assert legacy.ip == "10.0.0.1"
    assert legacy.category == "rate_limit_ip"
