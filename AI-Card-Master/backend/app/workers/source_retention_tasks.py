"""Celery beat task: Zero-Knowledge purge of heavy ZIP/originals after 24h."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from celery import Task

from app.application.source_retention_service import SourceRetentionService
from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.persistence.source_retention_repository import (
    SourceRetentionRepository,
)
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async
from app.services.s3_storage import (
    S3StorageConfigurationError,
    get_s3_storage,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class SourceRetentionTask(Task):
    """Retry policy for idempotent Zero-Knowledge retention sweeps."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


@celery_app.task(
    bind=True,
    base=SourceRetentionTask,
    name="privacy.purge_expired_sources",
)
def purge_expired_sources_task(self: Task) -> dict[str, int | list[str]]:
    """Delete heavy ZIP archives and original photos older than the retention window.

    Lightweight thumbnails remain for generation history. DB retention status
    becomes ``deleted`` after a successful S3 delete.
    """

    async def _task() -> dict[str, int | list[str]]:
        settings = get_settings()
        try:
            storage = get_s3_storage()
        except S3StorageConfigurationError:
            logger.error("Source retention: S3 is not configured; purge skipped.")
            return {
                "candidates": 0,
                "objects_deleted": 0,
                "objects_failed": 0,
                "records_marked_deleted": 0,
                "failed_keys": [],
            }

        async with SessionLocal() as session:
            service = SourceRetentionService(
                SourceRetentionRepository(session),
                storage,
                retention_hours=settings.source_retention_hours,
                batch_limit=settings.source_retention_batch_size,
            )
            result = await service.purge_expired_sources()
            return {
                "candidates": result.candidates,
                "objects_deleted": result.objects_deleted,
                "objects_failed": result.objects_failed,
                "records_marked_deleted": result.records_marked_deleted,
                "failed_keys": list(result.failed_keys),
            }

    return _run_async(_task)
