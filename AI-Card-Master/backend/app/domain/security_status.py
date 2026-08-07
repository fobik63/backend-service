"""Domain types for admin Security & Status dashboard (plan §62)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ApiProviderName = Literal["midjourney", "claude"]
ApiBalanceHealth = Literal[
    "ok",
    "low",
    "exhausted",
    "unreachable",
    "unknown",
    "misconfigured",
]
BlockedThreatAction = Literal["denied", "banned", "rate_limited"]


@dataclass(frozen=True, slots=True)
class HostResourceMetrics:
    """Live host CPU / memory snapshot."""

    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float


@dataclass(frozen=True, slots=True)
class RequestsPerSecondMetrics:
    """Rolling RPS estimate from Redis second buckets."""

    rps: float
    window_seconds: int
    requests_in_window: int


@dataclass(frozen=True, slots=True)
class ApiBalanceStatus:
    """External AI provider balance / reachability probe result."""

    provider: ApiProviderName
    status: ApiBalanceHealth
    balance: float | None = None
    currency: str | None = None
    unit: str | None = None
    message: str | None = None
    checked_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BlockedThreatEvent:
    """One blocked abuse / injection / rate-limit event for the admin feed."""

    id: str
    timestamp: datetime
    ip: str
    category: str
    path: str
    action: BlockedThreatAction
    http_status: int
    score: int | None = None
    api_key_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityStatusSnapshot:
    """Full Security & Status payload for REST / WebSocket."""

    collected_at: datetime
    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    rps: float
    rps_window_seconds: int
    midjourney: ApiBalanceStatus
    claude: ApiBalanceStatus
    blocked_threats: tuple[BlockedThreatEvent, ...]
    blocked_threats_count: int
