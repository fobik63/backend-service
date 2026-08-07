"""Celery tasks for «Глаз Бога»: sales spike → Claude Vision → money-trigger JSON."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.application.eye_of_god_bridge_service import (
    EyeOfGodTransientError,
    EyeOfGodValidationError,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.eye_of_god_factory import build_eye_of_god_bridge_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class EyeOfGodTask(Task):
    """Retry policy for idempotent Eye-of-God Vision jobs."""

    autoretry_for = (EyeOfGodTransientError, Exception)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


@celery_app.task(
    bind=True,
    base=EyeOfGodTask,
    name="claude.run_eye_of_god_vision",
)
def run_eye_of_god_vision_task(self: Task, job_id: str) -> dict[str, Any]:
    """Fetch current SKU photo → Claude 4.7 Vision → «Подтвержденный деньгами триггер»."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_eye_of_god_bridge_service(
                session,
                require_claude_client=True,
                enqueue_trigger=False,
            )
            try:
                job = await service.run_vision_pipeline(job_id=UUID(job_id))
            except EyeOfGodValidationError as exc:
                logger.warning(
                    "Eye-of-God Vision skipped job_id=%s reason=%s",
                    job_id,
                    exc,
                )
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(exc),
                }
            label = None
            if job.money_trigger_config:
                label = job.money_trigger_config.get("label")
            logger.info(
                "Eye-of-God finished job_id=%s status=%s label=%s triggers=%s",
                job.id,
                job.status.value,
                label,
                len(
                    (job.money_trigger_config or {}).get("conversion_elements") or []
                ),
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "article": job.article,
                "marketplace": job.marketplace,
                "label": label,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
                "conversion_element_count": len(
                    (job.money_trigger_config or {}).get("conversion_elements") or []
                ),
            }

    return _run_async(_task)
