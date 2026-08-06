"""Celery tasks for Claude 4.7 Vision & Chain-of-Thought reasoning."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.celery_app import celery_app
from app.infrastructure.claude_reasoning_factory import build_claude_reasoning_service
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ClaudeReasoningTask(Task):
    """Retry policy for idempotent Claude CoT jobs."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary around async Claude use cases."""

    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=ClaudeReasoningTask,
    name="claude.run_chain_of_thought",
)
def run_chain_of_thought_task(self: Task, job_id: str) -> dict[str, Any]:
    """Run Vision → text-alignment Chain-of-Thought for one job."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_claude_reasoning_service(
                session,
                require_claude_client=True,
            )
            job = await service.run_chain_of_thought(job_id=UUID(job_id))
            logger.info(
                "Claude CoT finished job_id=%s status=%s",
                job.id,
                job.status.value,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
            }

    return _run_async(_task)
