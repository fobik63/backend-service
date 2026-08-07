"""Celery tasks for competitor negative-review pain analysis."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.celery_app import celery_app
from app.infrastructure.pain_analysis_factory import build_pain_analysis_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class PainAnalysisTask(Task):
    """Retry policy for idempotent pain-analysis jobs."""

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
    base=PainAnalysisTask,
    name="claude.run_pain_analysis",
)
def run_pain_analysis_task(self: Task, job_id: str) -> dict[str, Any]:
    """Run junk filter → Claude pain-closing content generation."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            try:
                service = build_pain_analysis_service(
                    session,
                    require_claude_client=True,
                )
            except Exception:
                logger.warning(
                    "Pain analysis Claude client unavailable; "
                    "deterministic mode job_id=%s",
                    job_id,
                )
                service = build_pain_analysis_service(
                    session,
                    require_claude_client=False,
                )

            job = await service.run_analysis(job_id=UUID(job_id))
            pain_count = 0
            if job.analysis_result and isinstance(
                job.analysis_result.get("real_product_pains"), list
            ):
                pain_count = len(job.analysis_result["real_product_pains"])
            logger.info(
                "Pain analysis finished job_id=%s status=%s pains=%s",
                job.id,
                job.status.value,
                pain_count,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
                "pain_count": pain_count,
            }

    return _run_async(_task)
