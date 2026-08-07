"""Ports for Enterprise Audit Log & Event Tracking (plan §81)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.audit_log import (
    AuditArchiveResult,
    AuditEventRecord,
    AuditSearchQuery,
    AuditSearchResult,
)


class AuditLogRepositoryPort(Protocol):
    async def record_event(self, event: AuditEventRecord) -> UUID:
        """Persist one audit event; return ``event_id``."""

    async def search(self, query: AuditSearchQuery) -> AuditSearchResult:
        """Filter active (and optionally archived) events."""

    async def archive_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int = 1000,
    ) -> AuditArchiveResult:
        """Move events with ``created_at < cutoff`` into the archive table."""


class AuditEventExporterPort(Protocol):
    """Observability sink — OTel / Prometheus / ELK adapters implement this.

    Business emitters never depend on a concrete backend.
    """

    async def export(self, event: AuditEventRecord, *, event_id: UUID) -> None:
        """Best-effort fan-out; must not raise into the request path."""


class AuditLogServicePort(Protocol):
    async def record_event(self, event: AuditEventRecord) -> UUID | None:
        """Record + export; may return None when disabled / fail-open."""

    async def search_events(self, query: AuditSearchQuery) -> AuditSearchResult:
        """Admin search by user / type / date / IP / request_id."""

    async def archive_old_events(self) -> AuditArchiveResult:
        """Apply retention policy (active → archive)."""
