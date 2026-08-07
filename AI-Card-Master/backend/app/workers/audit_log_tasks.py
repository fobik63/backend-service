"""Celery tasks for Enterprise Audit Log archival (plan §81)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from celery import Task

from app.infrastructure.audit_log_factory import build_audit_log_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AuditLogTask(Task):
    """Retry policy for idempotent audit archival."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=AuditLogTask,
    name="audit.archive_old_events",
)
def archive_old_audit_events(self: Task) -> dict[str, Any]:
    """Move aged hot audit rows into ``audit_log_archives``."""

    async def _run() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_audit_log_service(session, fail_open=False)
            result = await service.archive_old_events()
            logger.info(
                "Audit archive complete archived=%s batches=%s cutoff=%s",
                result.archived_count,
                result.batches,
                result.cutoff.isoformat(),
            )
            return {
                "archived_count": result.archived_count,
                "batches": result.batches,
                "cutoff": result.cutoff.isoformat(),
            }

    return _run_async(_run)
