"""Composition root for Enterprise Audit Log (plan §81)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.audit_log_service import (
    AuditLogService,
    CompositeAuditEventExporter,
    NoopAuditEventExporter,
)
from app.core.config import Settings, get_settings
from app.domain.audit_log import (
    AuditArchivePolicy,
    AuditEventRecord,
    audit_event_to_export_payload,
)
from app.infrastructure.persistence.audit_log_repository import (
    AuditLogRepository,
    FailOpenAuditLogRepository,
)

logger = logging.getLogger(__name__)


class LoggingAuditEventExporter:
    """Structured-log sink — bridge toward ELK / Grafana Loki without domain changes."""

    async def export(self, event: AuditEventRecord, *, event_id: UUID) -> None:
        try:
            payload = audit_event_to_export_payload(event, event_id=event_id)
            logger.info(
                "audit_event event_type=%s status=%s event_id=%s request_id=%s user_id=%s",
                payload.get("event_type"),
                payload.get("status"),
                payload.get("event_id"),
                payload.get("request_id"),
                payload.get("user_id"),
                extra={"audit_event": payload},
            )
        except Exception:
            logger.debug("Audit structured export failed", exc_info=True)


def build_audit_archive_policy(settings: Settings | None = None) -> AuditArchivePolicy:
    cfg = settings or get_settings()
    return AuditArchivePolicy(
        retention_days=cfg.audit_log_retention_days,
        batch_size=cfg.audit_log_archive_batch_size,
        enabled=cfg.audit_log_archive_enabled,
    )


def build_audit_log_service(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    fail_open: bool = True,
) -> AuditLogService:
    """Build a request-scoped audit service bound to ``session``."""

    cfg = settings or get_settings()
    repo: AuditLogRepository | FailOpenAuditLogRepository = AuditLogRepository(session)
    if fail_open:
        repo = FailOpenAuditLogRepository(repo)

    exporters = []
    if cfg.audit_log_structured_export_enabled:
        exporters.append(LoggingAuditEventExporter())
    # Future: append OpenTelemetryAuditExporter / ElasticsearchAuditExporter here.
    if not exporters:
        exporter = NoopAuditEventExporter()
    elif len(exporters) == 1:
        exporter = exporters[0]
    else:
        exporter = CompositeAuditEventExporter(*exporters)

    return AuditLogService(
        repository=repo,
        exporter=exporter,
        archive_policy=build_audit_archive_policy(cfg),
        enabled=cfg.audit_log_enabled,
    )
