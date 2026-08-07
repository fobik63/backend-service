"""Celery tasks for Custom Brand LoRA training and polling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.infrastructure.brand_lora_factory import build_brand_lora_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BrandLoraTask(Task):
    """Retry policy for idempotent LoRA training tasks."""

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
    base=BrandLoraTask,
    name="brand_lora.start_training",
)
def start_training_task(self: Task, profile_id: str) -> dict[str, Any]:
    """Kick off provider training for a newly queued Brand LoRA profile."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_brand_lora_service(session)
            profile = await service.start_training_job(profile_id=UUID(profile_id))
            # Synthetic trainers finish immediately — promote to ready in-band.
            if profile.status.value == "training" and profile.provider_training_id:
                profile = await service.poll_training_job(profile_id=profile.id)
            logger.info(
                "Brand LoRA training kicked profile_id=%s status=%s",
                profile.id,
                profile.status.value,
            )
            return {
                "profile_id": str(profile.id),
                "status": profile.status.value,
                "progress": profile.training_progress,
            }

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=BrandLoraTask,
    name="brand_lora.poll_active_trainings",
)
def poll_active_trainings_task(self: Task) -> dict[str, Any]:
    """Advance queued/training Brand LoRA profiles toward ready/failed."""

    async def _task() -> dict[str, Any]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_brand_lora_service(session)
            processed = await service.poll_active_trainings(
                limit=settings.brand_lora_poll_batch_size
            )
            return {"processed": processed}

    return _run_async(_task)
