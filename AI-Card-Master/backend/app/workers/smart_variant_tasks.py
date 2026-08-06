"""Celery tasks for Smart Variant Sync recolor and completion polling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.smart_variant_factory import build_smart_variant_service
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class SmartVariantTask(Task):
    """Retry policy for idempotent recolor / poll tasks."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary around async smart-variant use cases."""

    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=SmartVariantTask,
    name="smart_variant.recolor_and_enqueue",
)
def recolor_and_enqueue_task(
    self: Task,
    sync_id: str,
    subscription_status: str,
) -> dict[str, Any]:
    """Recolor fabric for each target color and enqueue generation jobs."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_smart_variant_service(session)
            sync = await service.recolor_and_enqueue(
                sync_id=UUID(sync_id),
                subscription_status=subscription_status,
            )
            logger.info(
                "Smart variant recolor finished sync_id=%s status=%s total=%s",
                sync.id,
                sync.status.value,
                sync.total_items,
            )
            return {
                "sync_id": str(sync.id),
                "status": sync.status.value,
                "total_items": sync.total_items,
            }

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=SmartVariantTask,
    name="smart_variant.poll_active_syncs",
)
def poll_active_syncs_task(self: Task) -> dict[str, int]:
    """Refresh running syncs and notify when all color variants are ready."""

    async def _task() -> dict[str, int]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_smart_variant_service(session)
            result = await service.poll_active_syncs(
                limit=settings.smart_variant_poll_batch_size,
            )
            logger.info("Smart variant poll active syncs: %s", result)
            return result

    return _run_async(_task)
