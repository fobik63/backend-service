"""Application service: Enterprise Audit Log (plan §81)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.audit_log import (
    AuditEventExporterPort,
    AuditLogRepositoryPort,
)
from app.domain.audit_log import (
    AuditArchivePolicy,
    AuditArchiveResult,
    AuditEventRecord,
    AuditSearchQuery,
    AuditSearchResult,
    normalize_audit_event,
)


class NoopAuditEventExporter:
    """Default exporter — replace with OTel / ELK / Prometheus adapters later."""

    async def export(self, event: AuditEventRecord, *, event_id: UUID) -> None:
        _ = event, event_id


class CompositeAuditEventExporter:
    """Fan-out to multiple sinks without touching business emitters."""

    def __init__(self, *exporters: AuditEventExporterPort) -> None:
        self._exporters = exporters

    async def export(self, event: AuditEventRecord, *, event_id: UUID) -> None:
        for exporter in self._exporters:
            await exporter.export(event, event_id=event_id)


class AuditLogService:
    """Orchestrates audit persistence, search, archival, and observability export."""

    def __init__(
        self,
        *,
        repository: AuditLogRepositoryPort,
        exporter: AuditEventExporterPort | None = None,
        archive_policy: AuditArchivePolicy | None = None,
        enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._exporter: AuditEventExporterPort = exporter or NoopAuditEventExporter()
        self._archive_policy = archive_policy or AuditArchivePolicy()
        self._enabled = enabled

    async def record_event(self, event: AuditEventRecord) -> UUID | None:
        if not self._enabled:
            return None
        normalized = normalize_audit_event(event)
        if normalized.created_at is None:
            normalized = AuditEventRecord(
                event_type=normalized.event_type,
                status=normalized.status,
                user_id=normalized.user_id,
                telegram_id=normalized.telegram_id,
                ip=normalized.ip,
                visitor_id=normalized.visitor_id,
                user_agent=normalized.user_agent,
                endpoint=normalized.endpoint,
                http_method=normalized.http_method,
                request_id=normalized.request_id,
                duration_ms=normalized.duration_ms,
                actor_type=normalized.actor_type,
                message=normalized.message,
                metadata=normalized.metadata,
                created_at=datetime.now(UTC),
                event_id=normalized.event_id,
            )
        event_id = await self._repository.record_event(normalized)
        await self._exporter.export(normalized, event_id=event_id)
        return event_id

    async def search_events(self, query: AuditSearchQuery) -> AuditSearchResult:
        limit = max(1, min(int(query.limit), 500))
        offset = max(0, int(query.offset))
        safe = AuditSearchQuery(
            user_id=query.user_id,
            event_type=query.event_type,
            ip=query.ip.strip()[:64] if query.ip else None,
            request_id=query.request_id.strip()[:64] if query.request_id else None,
            created_from=query.created_from,
            created_to=query.created_to,
            include_archived=query.include_archived,
            limit=limit,
            offset=offset,
        )
        return await self._repository.search(safe)

    async def archive_old_events(
        self,
        *,
        now: datetime | None = None,
    ) -> AuditArchiveResult:
        policy = self._archive_policy
        if not policy.enabled or policy.retention_days <= 0:
            moment = now or datetime.now(UTC)
            return AuditArchiveResult(archived_count=0, cutoff=moment, batches=0)

        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        else:
            moment = moment.astimezone(UTC)
        cutoff = moment - timedelta(days=policy.retention_days)

        total = 0
        batches = 0
        while True:
            result = await self._repository.archive_before(
                cutoff=cutoff,
                batch_size=max(1, policy.batch_size),
            )
            batches += 1
            total += result.archived_count
            if result.archived_count < policy.batch_size:
                break
            # Safety: avoid infinite loops if retention is misconfigured.
            if batches >= 1000:
                break
        return AuditArchiveResult(archived_count=total, cutoff=cutoff, batches=batches)
