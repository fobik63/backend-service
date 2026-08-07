"""Celery tasks for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.ai_strategy_factory import build_ai_strategy_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AiStrategyTask(Task):
    """Retry policy for idempotent AI Strategy jobs."""

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
    base=AiStrategyTask,
    name="claude.run_ai_strategy_plan",
)
def run_ai_strategy_plan_task(self: Task, job_id: str) -> dict[str, Any]:
    """Run user-vs-leader compare → Claude killer plan."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            try:
                service = build_ai_strategy_service(
                    session,
                    require_claude_client=True,
                )
            except Exception:
                logger.warning(
                    "AI Strategy Claude client unavailable; deterministic mode job_id=%s",
                    job_id,
                )
                service = build_ai_strategy_service(
                    session,
                    require_claude_client=False,
                )

            job = await service.run_strategy_plan(job_id=UUID(job_id))
            rec_count = 0
            if job.plan_result and isinstance(job.plan_result.get("recommendations"), list):
                rec_count = len(job.plan_result["recommendations"])
            logger.info(
                "AI Strategy finished job_id=%s status=%s recommendations=%s",
                job.id,
                job.status.value,
                rec_count,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
                "recommendation_count": rec_count,
            }

    return _run_async(_task)
