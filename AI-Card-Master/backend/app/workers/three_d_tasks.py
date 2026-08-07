"""Celery tasks for async 3D generation (hold → provider → S3 → settle)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.three_d_factory import build_three_d_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ThreeDTaskBase(Task):
    """Retry policy for idempotent 3D pipeline tasks."""

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
    base=ThreeDTaskBase,
    name="three_d.process_generation_task",
)
def process_3d_generation_task(self: Task, task_id: str) -> dict[str, Any]:
    """Hold coins, submit to the 3D engine, poll (or await webhook), finalize."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_three_d_service(session)
            if self.request.id:
                await service.attach_celery_task(
                    task_id=UUID(task_id),
                    celery_task_id=str(self.request.id),
                )
            result = await service.process_generation_task(UUID(task_id))
            logger.info(
                "3D generation finished task_id=%s status=%s",
                task_id,
                result.get("status"),
            )
            return result

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=ThreeDTaskBase,
    name="three_d.poll_active_tasks",
)
def poll_active_3d_tasks(self: Task) -> dict[str, Any]:
    """Beat: advance PROCESSING tasks (webhook mode / recovery)."""

    async def _task() -> dict[str, Any]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_three_d_service(session)
            return await service.poll_active_tasks(
                limit=settings.three_d_poll_batch_size
            )

    return _run_async(_task)
