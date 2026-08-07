"""Fail-open helpers for Enterprise Audit Log emitters (plan §81)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.request_context import merge_context_into_kwargs
from app.domain.audit_log import AuditEventRecord, AuditEventStatus, AuditEventType
from app.infrastructure.persistence.audit_log_repository import AuditLogRepository
from app.models.database import SessionLocal

logger = logging.getLogger(__name__)


def _coerce_event_type(event_type: AuditEventType | str) -> AuditEventType:
    if isinstance(event_type, AuditEventType):
        return event_type
    return AuditEventType(str(event_type))


def _coerce_status(status: AuditEventStatus | str) -> AuditEventStatus:
    if isinstance(status, AuditEventStatus):
        return status
    try:
        return AuditEventStatus(str(status))
    except ValueError:
        return AuditEventStatus.SUCCESS


async def record_audit_event(
    *,
    event_type: AuditEventType | str,
    status: AuditEventStatus | str = AuditEventStatus.SUCCESS,
    user_id: UUID | None = None,
    telegram_id: int | None = None,
    ip: str | None = None,
    visitor_id: str | None = None,
    user_agent: str | None = None,
    endpoint: str | None = None,
    http_method: str | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
    actor_type: str = "user",
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UUID | None:
    """Persist one audit event on its own DB session (never raises).

    Pulls request_id / IP / visitorId / UA / endpoint from ContextVar when
    omitted — safe for Celery/webhooks (those fields stay null).
    """

    try:
        from app.core.config import get_settings

        if not get_settings().audit_log_enabled:
            return None

        ctx_fields = merge_context_into_kwargs(
            request_id=request_id,
            ip=ip,
            visitor_id=visitor_id,
            user_agent=user_agent,
            endpoint=endpoint,
            http_method=http_method,
        )
        event = AuditEventRecord(
            event_type=_coerce_event_type(event_type),
            status=_coerce_status(status),
            user_id=user_id,
            telegram_id=telegram_id,
            ip=ctx_fields.get("ip"),
            visitor_id=ctx_fields.get("visitor_id"),
            user_agent=ctx_fields.get("user_agent"),
            endpoint=ctx_fields.get("endpoint"),
            http_method=ctx_fields.get("http_method"),
            request_id=ctx_fields.get("request_id"),
            duration_ms=duration_ms,
            actor_type=actor_type,
            message=message,
            metadata=metadata,
        )
        async with SessionLocal() as session:
            return await AuditLogRepository(session).record_event(event)
    except Exception:
        logger.warning("Failed to persist audit event", exc_info=True)
        return None
