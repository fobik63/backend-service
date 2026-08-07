"""Pydantic schemas for Enterprise Audit Log admin API (plan §81)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.audit_log import AuditArchiveResult, AuditSearchResult


class StrictAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class AuditEventResponse(StrictAuditModel):
    event_id: UUID
    user_id: UUID | None = None
    event_type: str
    status: str
    ip: str | None = None
    visitor_id: str | None = None
    telegram_id: int | None = None
    user_agent: str | None = None
    endpoint: str | None = None
    http_method: str | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    actor_type: str = "user"
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    archived: bool = False


class AuditSearchResponse(StrictAuditModel):
    """GET /api/v1/admin/audit-logs payload."""

    items: list[AuditEventResponse]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)


class AuditArchiveResponse(StrictAuditModel):
    archived_count: int = Field(..., ge=0)
    cutoff: datetime
    batches: int = Field(..., ge=0)


def search_result_to_response(result: AuditSearchResult) -> AuditSearchResponse:
    return AuditSearchResponse(
        items=[
            AuditEventResponse(
                event_id=item.event_id,
                user_id=item.user_id,
                event_type=item.event_type,
                status=item.status,
                ip=item.ip,
                visitor_id=item.visitor_id,
                telegram_id=item.telegram_id,
                user_agent=item.user_agent,
                endpoint=item.endpoint,
                http_method=item.http_method,
                request_id=item.request_id,
                duration_ms=item.duration_ms,
                actor_type=item.actor_type,
                message=item.message,
                metadata=item.metadata,
                created_at=item.created_at,
                archived=item.archived,
            )
            for item in result.items
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


def archive_result_to_response(result: AuditArchiveResult) -> AuditArchiveResponse:
    return AuditArchiveResponse(
        archived_count=result.archived_count,
        cutoff=result.cutoff,
        batches=result.batches,
    )
