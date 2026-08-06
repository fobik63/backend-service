"""Celery tasks for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.celery_app import celery_app
from app.infrastructure.oracle_factory import build_oracle_service
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class OracleTask(Task):
    """Retry policy for idempotent Oracle prediction jobs."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary around async Oracle use cases."""

    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=OracleTask,
    name="claude.run_oracle_prediction",
)
def run_oracle_prediction_task(self: Task, job_id: str) -> dict[str, Any]:
    """Run demand/supply gap scan → Claude enrichment → niche alerts."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            # Prefer Claude when the key is present; otherwise emit
            # deterministic niche alerts without failing the job.
            try:
                service = build_oracle_service(
                    session,
                    require_claude_client=True,
                )
            except Exception:
                logger.warning(
                    "Oracle Claude client unavailable; deterministic mode job_id=%s",
                    job_id,
                )
                service = build_oracle_service(
                    session,
                    require_claude_client=False,
                )

            job = await service.run_oracle_prediction(job_id=UUID(job_id))
            logger.info(
                "Oracle finished job_id=%s status=%s gaps=%s notifications=%s",
                job.id,
                job.status.value,
                len((job.scan_report or {}).get("opportunities") or [])
                if job.scan_report
                else 0,
                len(job.notifications or []),
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
                "opportunity_count": len(
                    (job.prediction_result or {}).get("opportunities") or []
                ),
                "notification_count": len(job.notifications or []),
            }

    return _run_async(_task)
