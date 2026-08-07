"""Short Celery entrypoints for the durable generation state machine."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task
from sqlalchemy import select

from app.application.generation_service import GenerationApplicationService
from app.core.config import get_settings
from app.domain.generation import GenerationErrorCode, GenerationErrorInfo, GenerationJobStatus
from app.domain.silent_ban import SHADOW_LOAD_ERROR_MESSAGE, pick_shadow_delay_seconds
from app.infrastructure.ai_engine_facade import (
    build_default_ai_engine,
    build_default_image_pipeline,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.database import SessionLocal
from app.models.generation_job import GenerationJob
from app.models.user import User
from app.services.ai_engine import (
    get_healthy_async_midjourney_providers,
    get_stable_diffusion_adapter,
)
from app.services.marketplace_text import (
    MarketplaceTextConfigurationError,
    get_marketplace_text_service,
)
from app.services.s3_storage import get_s3_storage
from app.workers.async_runtime import run_worker_async

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


class ShadowGenerationTask(Task):
    """No retries — shadow failures must look like a one-shot provider timeout."""

    autoretry_for = ()
    max_retries = 0
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


async def _build_service(
    repository: GenerationRepository,
) -> GenerationApplicationService:
    text_provider = None
    try:
        text_provider = get_marketplace_text_service()
    except MarketplaceTextConfigurationError:
        logger.warning("Marketplace text generation is disabled: LLM is not configured.")

    async def _load_brand_dna_claude_context(user_id: UUID) -> str | None:
        from app.infrastructure.brand_dna_factory import build_brand_dna_service

        dna = await build_brand_dna_service(repository._session).get_active_context(
            user_id=user_id
        )
        return dna.claude_context if dna is not None else None

    def _on_generation_completed(user_id: UUID) -> None:
        from app.workers.brand_dna_tasks import enqueue_brand_dna_refresh

        enqueue_brand_dna_refresh(user_id)

    return GenerationApplicationService(
        repository=repository,
        storage=get_s3_storage(),
        async_providers=await get_healthy_async_midjourney_providers(),
        immediate_provider=get_stable_diffusion_adapter(),
        text_provider=text_provider,
        brand_dna_claude_context_loader=_load_brand_dna_claude_context,
        on_generation_completed=_on_generation_completed,
        ai_engine=build_default_ai_engine(),
        image_pipeline=build_default_image_pipeline(),
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
    base=ShadowGenerationTask,
    name="generation.submit_job_shadow",
)
def submit_job_shadow_task(self: Task, job_id: str) -> None:
    """Silent-ban path: never call AI; sleep then fail with a fake load timeout."""

    async def _task() -> None:
        settings = get_settings()
        delay = pick_shadow_delay_seconds(
            min_seconds=settings.silent_ban_shadow_delay_min_seconds,
            max_seconds=settings.silent_ban_shadow_delay_max_seconds,
        )
        logger.info(
            "Shadow generation delay=%ss job_id=%s (silent ban; no AI)",
            delay,
            job_id,
        )
        await asyncio.sleep(delay)
        async with SessionLocal() as session:
            repository = GenerationRepository(session)
            work = await repository.get_work_item(UUID(job_id))
            if work is None or work.status in {
                GenerationJobStatus.COMPLETED,
                GenerationJobStatus.FAILED,
            }:
                return
            await repository.set_job_status(
                UUID(job_id),
                GenerationJobStatus.SUBMITTING,
                progress=8,
            )
            await repository.fail_job(
                UUID(job_id),
                GenerationErrorInfo(
                    code=GenerationErrorCode.TRANSIENT,
                    message=SHADOW_LOAD_ERROR_MESSAGE,
                    retryable=True,
                ),
            )

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
                    task_name, kwargs = await _outbox_task(
                        session,
                        message.event_type.value,
                        message.payload,
                        silent_ban_enabled=settings.silent_ban_enabled,
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


async def _outbox_task(
    session: Any,
    event_type: str,
    payload: dict[str, Any],
    *,
    silent_ban_enabled: bool,
) -> tuple[str, dict[str, Any]]:
    if event_type == "submit_job":
        job_id = str(payload["job_id"])
        task_name = "generation.submit_job"
        if silent_ban_enabled and await _job_owner_is_flagged(session, job_id):
            task_name = "generation.submit_job_shadow"
        return task_name, {"job_id": job_id}
    if event_type == "process_webhook":
        return "generation.process_webhook", {
            "webhook_event_id": str(payload["webhook_event_id"])
        }
    if event_type == "finalize_job":
        return "generation.finalize_job", {"job_id": str(payload["job_id"])}
    if event_type == "recover_job":
        return "generation.recover_stalled", {}
    raise ValueError(f"Unsupported outbox event type '{event_type}'.")


async def _job_owner_is_flagged(session: Any, job_id: str) -> bool:
    """True when the generation job belongs to a silently flagged user."""

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        return False
    result = await session.execute(
        select(User.is_flagged)
        .join(GenerationJob, GenerationJob.user_id == User.id)
        .where(GenerationJob.id == job_uuid)
    )
    flagged = result.scalar_one_or_none()
    return bool(flagged)
