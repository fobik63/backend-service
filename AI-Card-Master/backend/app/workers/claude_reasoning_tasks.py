"""Celery tasks for Claude 4.7 Vision & Chain-of-Thought reasoning."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.application.claude_reasoning_service import ClaudeReasoningTransientError
from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.claude_reasoning_factory import build_claude_reasoning_service
from app.infrastructure.persistence.claude_reasoning_repository import (
    ClaudeReasoningRepository,
)
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

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
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


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
            try:
                job = await service.run_chain_of_thought(job_id=UUID(job_id))
            except ClaudeReasoningTransientError:
                raise
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


@celery_app.task(
    bind=True,
    base=ClaudeReasoningTask,
    name="claude.dispatch_outbox",
)
def dispatch_outbox_task(self: Task) -> int:
    """Publish committed Claude outbox rows to the reasoning queue."""

    async def _task() -> int:
        settings = get_settings()
        published = 0
        async with SessionLocal() as session:
            repository = ClaudeReasoningRepository(session)
            messages = await repository.claim_outbox(
                limit=settings.claude_47_outbox_batch_size
            )
            for message in messages:
                try:
                    job_id = str(message.payload.get("job_id") or message.aggregate_id)
                    async_result = await asyncio.to_thread(
                        celery_app.send_task,
                        "claude.run_chain_of_thought",
                        args=[job_id],
                        queue="claude.reasoning",
                    )
                    service = build_claude_reasoning_service(session)
                    await service.attach_celery_task(
                        job_id=UUID(job_id),
                        celery_task_id=str(async_result.id),
                    )
                    await repository.mark_outbox_published(message.id)
                    published += 1
                except Exception as exc:
                    logger.exception(
                        "Claude outbox publish failed for message %s",
                        message.id,
                    )
                    await repository.mark_outbox_failed(message.id, str(exc))
        return published

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=ClaudeReasoningTask,
    name="claude.recover_stalled",
)
def recover_stalled_task(self: Task) -> dict[str, int]:
    """Re-enqueue stalled Claude analysis jobs via the outbox."""

    async def _task() -> dict[str, int]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_claude_reasoning_service(session)
            recovered = await service.recover_stalled(
                limit=settings.claude_47_recovery_batch_size
            )
            return {"recovered": recovered}

    return _run_async(_task)
