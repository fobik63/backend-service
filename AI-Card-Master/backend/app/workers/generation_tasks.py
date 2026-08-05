"""Short Celery entrypoints for the durable generation state machine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.application.generation_service import GenerationApplicationService
from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.infrastructure.redis import close_redis_client
from app.models.database import SessionLocal, engine
from app.services.ai_engine import (
    close_ai_engine,
    get_healthy_async_midjourney_providers,
    get_stable_diffusion_adapter,
)
from app.services.s3_storage import get_s3_storage

logger = logging.getLogger(__name__)
T = TypeVar("T")


class DurableGenerationTask(Task):
    """Common retry policy for idempotent DB-backed tasks."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 8
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery's required sync boundary around fully asynchronous use cases."""

    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await close_ai_engine()
            await close_redis_client()
            await engine.dispose()

    return asyncio.run(_execute())


async def _build_service(
    repository: GenerationRepository,
) -> GenerationApplicationService:
    return GenerationApplicationService(
        repository=repository,
        storage=get_s3_storage(),
        async_providers=await get_healthy_async_midjourney_providers(),
        immediate_provider=get_stable_diffusion_adapter(),
    )


@celery_app.task(
    bind=True,
    base=DurableGenerationTask,
    name="generation.submit_job",
)
def submit_job_task(self: Task, job_id: str) -> None:
    """Submit provider work; asynchronous providers return after job creation."""

    async def _task() -> None:
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            service = await _build_service(repository)
            await service.submit_job(UUID(job_id))

    _run_async(_task)


@celery_app.task(
    bind=True,
    base=DurableGenerationTask,
    name="generation.process_webhook",
)
def process_webhook_task(self: Task, webhook_event_id: str) -> None:
    """Resume a generation from one persisted provider callback."""

    async def _task() -> None:
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            service = await _build_service(repository)
            await service.process_webhook(UUID(webhook_event_id))

    _run_async(_task)


@celery_app.task(
    bind=True,
    base=DurableGenerationTask,
    name="generation.finalize_job",
)
def finalize_job_task(self: Task, job_id: str) -> None:
    """Create the ZIP archive only after every slide is durable in S3."""

    async def _task() -> None:
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            service = await _build_service(repository)
            await service.finalize_job(UUID(job_id))

    _run_async(_task)


@celery_app.task(
    bind=True,
    base=DurableGenerationTask,
    name="generation.recover_stalled",
)
def recover_stalled_task(self: Task) -> None:
    """Run one bounded recovery pass; no resident polling or sleeping."""

    async def _task() -> None:
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            service = await _build_service(repository)
            await service.recover_stalled()

    _run_async(_task)


@celery_app.task(
    bind=True,
    base=DurableGenerationTask,
    name="generation.dispatch_outbox",
)
def dispatch_outbox_task(self: Task) -> int:
    """Publish committed DB outbox rows to their dedicated Celery queues."""

    async def _task() -> int:
        settings = get_settings()
        published = 0
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            messages = await repository.claim_outbox(
                limit=settings.celery_outbox_batch_size
            )
            for message in messages:
                try:
                    task_name, kwargs = _outbox_task(
                        message.event_type.value, message.payload
                    )
                    await asyncio.to_thread(
                        celery_app.send_task,
                        task_name,
                        kwargs=kwargs,
                    )
                    await repository.mark_outbox_published(message.id)
                    published += 1
                except Exception as exc:
                    logger.exception("Outbox publish failed for message %s", message.id)
                    await repository.mark_outbox_failed(message.id, str(exc))
        return published

    return _run_async(_task)


def _outbox_task(
    event_type: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if event_type == "submit_job":
        return "generation.submit_job", {"job_id": str(payload["job_id"])}
    if event_type == "process_webhook":
        return "generation.process_webhook", {
            "webhook_event_id": str(payload["webhook_event_id"])
        }
    if event_type == "finalize_job":
        return "generation.finalize_job", {"job_id": str(payload["job_id"])}
    if event_type == "recover_job":
        return "generation.recover_stalled", {}
    raise ValueError(f"Unsupported outbox event type '{event_type}'.")
