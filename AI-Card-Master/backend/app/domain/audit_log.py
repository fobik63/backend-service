"""Domain types for Enterprise Audit Log & Event Tracking (plan §81).

Business logic depends only on these types + ports. Observability backends
(Grafana / Prometheus / OpenTelemetry / ELK) plug in via ``AuditEventExporterPort``
without changing emitters or use-cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AuditEventType(StrEnum):
    """Canonical audit event taxonomy (stable wire values)."""

    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    PAYMENT_PURCHASED = "payment.purchased"
    GENERATION_STARTED = "generation.started"
    CREDIT_DEDUCTED = "credit.deducted"
    CREDIT_REFUNDED = "credit.refunded"
    TARIFF_CHANGED = "tariff.changed"
    ACCOUNT_DELETED = "account.deleted"
    SETTINGS_CHANGED = "settings.changed"
    PROMO_USED = "promo.used"
    REFERRAL_APPLIED = "referral.applied"
    REFERRAL_BONUS_CREDITED = "referral.bonus_credited"
    ADMIN_ACTION = "admin.action"
    ADMIN_ENDPOINT_ACCESS = "admin.endpoint_access"
    SECURITY_ERROR = "security.error"
    SECURITY_SUSPICIOUS = "security.suspicious"
    SYSTEM_EVENT = "system.event"


class AuditEventStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    """One immutable audit event ready for persistence + export."""

    event_type: AuditEventType
    status: AuditEventStatus = AuditEventStatus.SUCCESS
    user_id: UUID | None = None
    telegram_id: int | None = None
    ip: str | None = None
    visitor_id: str | None = None
    user_agent: str | None = None
    endpoint: str | None = None
    http_method: str | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    actor_type: str = "user"
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuditSearchQuery:
    """Admin search filters (all optional; AND semantics)."""

    user_id: UUID | None = None
    event_type: AuditEventType | None = None
    ip: str | None = None
    request_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    include_archived: bool = False
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class AuditEventView:
    """Search hit returned to admin API / exporters."""

    event_id: UUID
    user_id: UUID | None
    event_type: str
    status: str
    ip: str | None
    visitor_id: str | None
    telegram_id: int | None
    user_agent: str | None
    endpoint: str | None
    http_method: str | None
    request_id: str | None
    duration_ms: int | None
    actor_type: str
    message: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    archived: bool = False


@dataclass(frozen=True, slots=True)
class AuditSearchResult:
    items: tuple[AuditEventView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class AuditArchivePolicy:
    """Retention: move rows older than ``retention_days`` into archive table."""

    retention_days: int = 90
    batch_size: int = 1000
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class AuditArchiveResult:
    archived_count: int
    cutoff: datetime
    batches: int = 1


def normalize_audit_event(event: AuditEventRecord) -> AuditEventRecord:
    """Clamp string lengths and normalize enums before persistence."""

    def _clip(value: str | None, max_len: int) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned[:max_len]

    meta = event.metadata
    if meta is not None and not isinstance(meta, dict):
        meta = {"value": str(meta)}

    return AuditEventRecord(
        event_type=event.event_type,
        status=event.status,
        user_id=event.user_id,
        telegram_id=event.telegram_id,
        ip=_clip(event.ip, 64),
        visitor_id=_clip(event.visitor_id, 128),
        user_agent=_clip(event.user_agent, 512),
        endpoint=_clip(event.endpoint, 512),
        http_method=_clip(event.http_method, 16),
        request_id=_clip(event.request_id, 64),
        duration_ms=None if event.duration_ms is None else max(0, int(event.duration_ms)),
        actor_type=_clip(event.actor_type, 32) or "user",
        message=_clip(event.message, 2000),
        metadata=meta,
        created_at=event.created_at,
        event_id=event.event_id,
    )


def audit_event_to_export_payload(event: AuditEventRecord, *, event_id: UUID) -> dict[str, Any]:
    """Stable JSON-ish dict for OTel / ELK / Prometheus label exporters."""

    return {
        "event_id": str(event_id),
        "event_type": event.event_type.value,
        "status": event.status.value,
        "user_id": str(event.user_id) if event.user_id else None,
        "telegram_id": event.telegram_id,
        "ip": event.ip,
        "visitor_id": event.visitor_id,
        "user_agent": event.user_agent,
        "endpoint": event.endpoint,
        "http_method": event.http_method,
        "request_id": event.request_id,
        "duration_ms": event.duration_ms,
        "actor_type": event.actor_type,
        "message": event.message,
        "metadata": event.metadata or {},
        "timestamp": (event.created_at.isoformat() if event.created_at else None),
    }


__all__ = [
    "AuditArchivePolicy",
    "AuditArchiveResult",
    "AuditEventRecord",
    "AuditEventStatus",
    "AuditEventType",
    "AuditEventView",
    "AuditSearchQuery",
    "AuditSearchResult",
    "StrictDomainModel",
    "audit_event_to_export_payload",
    "normalize_audit_event",
]
