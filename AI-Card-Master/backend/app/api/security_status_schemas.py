"""Pydantic schemas and snapshot mapping for Security & Status (plan §62)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.security_status import SecurityStatusSnapshot


class StrictSecurityStatusModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class ApiBalanceStatusResponse(StrictSecurityStatusModel):
    provider: Literal["midjourney", "claude"]
    status: Literal[
        "ok",
        "low",
        "exhausted",
        "unreachable",
        "unknown",
        "misconfigured",
    ]
    balance: float | None = None
    currency: str | None = None
    unit: str | None = None
    message: str | None = None
    checked_at: datetime | None = None


class BlockedThreatEventResponse(StrictSecurityStatusModel):
    id: str
    timestamp: datetime
    ip: str
    category: str
    path: str
    action: Literal["denied", "banned", "rate_limited"]
    http_status: int
    score: int | None = None
    api_key_fingerprint: str | None = None


class SecurityStatusResponse(StrictSecurityStatusModel):
    """Live Security & Status payload for admin panel."""

    collected_at: datetime
    cpu_percent: float = Field(..., ge=0)
    ram_percent: float = Field(..., ge=0)
    ram_used_mb: float = Field(..., ge=0)
    ram_total_mb: float = Field(..., ge=0)
    rps: float = Field(..., ge=0)
    rps_window_seconds: int = Field(..., ge=1)
    midjourney: ApiBalanceStatusResponse
    claude: ApiBalanceStatusResponse
    blocked_threats: list[BlockedThreatEventResponse]
    blocked_threats_count: int = Field(..., ge=0)


class BlockedThreatsLogResponse(StrictSecurityStatusModel):
    """Dedicated JSON log of the last N blocked threats."""

    threats: list[BlockedThreatEventResponse]
    count: int = Field(..., ge=0)


def snapshot_to_response(snapshot: SecurityStatusSnapshot) -> SecurityStatusResponse:
    return SecurityStatusResponse(
        collected_at=snapshot.collected_at,
        cpu_percent=snapshot.cpu_percent,
        ram_percent=snapshot.ram_percent,
        ram_used_mb=snapshot.ram_used_mb,
        ram_total_mb=snapshot.ram_total_mb,
        rps=snapshot.rps,
        rps_window_seconds=snapshot.rps_window_seconds,
        midjourney=ApiBalanceStatusResponse(
            provider=snapshot.midjourney.provider,
            status=snapshot.midjourney.status,
            balance=snapshot.midjourney.balance,
            currency=snapshot.midjourney.currency,
            unit=snapshot.midjourney.unit,
            message=snapshot.midjourney.message,
            checked_at=snapshot.midjourney.checked_at,
        ),
        claude=ApiBalanceStatusResponse(
            provider=snapshot.claude.provider,
            status=snapshot.claude.status,
            balance=snapshot.claude.balance,
            currency=snapshot.claude.currency,
            unit=snapshot.claude.unit,
            message=snapshot.claude.message,
            checked_at=snapshot.claude.checked_at,
        ),
        blocked_threats=[
            BlockedThreatEventResponse(
                id=item.id,
                timestamp=item.timestamp,
                ip=item.ip,
                category=item.category,
                path=item.path,
                action=item.action,
                http_status=item.http_status,
                score=item.score,
                api_key_fingerprint=item.api_key_fingerprint,
            )
            for item in snapshot.blocked_threats
        ],
        blocked_threats_count=snapshot.blocked_threats_count,
    )


def snapshot_to_dict(snapshot: SecurityStatusSnapshot) -> dict[str, Any]:
    """JSON-ready dict for WebSocket frames."""

    return snapshot_to_response(snapshot).model_dump(mode="json")
