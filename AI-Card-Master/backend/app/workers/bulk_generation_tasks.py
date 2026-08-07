"""Celery tasks for Bulk Generation unpack and completion polling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.infrastructure.bulk_generation_factory import build_bulk_generation_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BulkGenerationTask(Task):
    """Retry policy for idempotent bulk unpack / poll tasks."""

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
    base=BulkGenerationTask,
    name="bulk.unpack_and_enqueue",
)
def unpack_and_enqueue_task(
    self: Task,
    batch_id: str,
    subscription_status: str,
) -> dict[str, Any]:
    """Unpack the source ZIP and enqueue one generation job per product."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_bulk_generation_service(session)
            batch = await service.unpack_and_enqueue(
                batch_id=UUID(batch_id),
                subscription_status=subscription_status,
            )
            logger.info(
                "Bulk unpack finished batch_id=%s status=%s total=%s",
                batch.id,
                batch.status.value,
                batch.total_items,
            )
            return {
                "batch_id": str(batch.id),
                "status": batch.status.value,
                "total_items": batch.total_items,
            }

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=BulkGenerationTask,
    name="bulk.poll_active_batches",
)
def poll_active_batches_task(self: Task) -> dict[str, int]:
    """Refresh running batches and notify when the whole party is ready."""

    async def _task() -> dict[str, int]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_bulk_generation_service(session)
            result = await service.poll_active_batches(
                limit=settings.bulk_generation_poll_batch_size,
            )
            logger.info("Bulk poll active batches: %s", result)
            return result

    return _run_async(_task)
