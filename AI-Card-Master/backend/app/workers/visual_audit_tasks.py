"""Celery tasks for Claude 4.7 intelligent visual audit."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.celery_app import celery_app
from app.infrastructure.visual_audit_factory import build_visual_audit_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class VisualAuditTask(Task):
    """Retry policy for idempotent visual-audit jobs."""

    autoretry_for = (Exception,)
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
    base=VisualAuditTask,
    name="claude.run_visual_audit",
)
def run_visual_audit_task(self: Task, job_id: str) -> dict[str, Any]:
    """Run survivor-bias filter → Rising Star Vision → generator JSON."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_visual_audit_service(
                session,
                require_claude_client=True,
            )
            job = await service.run_visual_audit(job_id=UUID(job_id))
            logger.info(
                "Visual audit finished job_id=%s status=%s rising=%s",
                job.id,
                job.status.value,
                len((job.filter_report or {}).get("rising_stars") or [])
                if job.filter_report
                else 0,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
                "rising_star_count": len(
                    (job.generator_config or {}).get("rising_star_skus") or []
                ),
                "trigger_count": len(
                    (job.generator_config or {}).get("money_validated_triggers") or []
                ),
            }

    return _run_async(_task)
