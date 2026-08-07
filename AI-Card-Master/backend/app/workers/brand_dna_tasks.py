"""Celery tasks for BrandDNA refresh after successful generations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.infrastructure.brand_dna_factory import build_brand_dna_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BrandDNATask(Task):
    """Retry policy for idempotent BrandDNA analysis tasks."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 120
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary around async BrandDNA use cases."""

    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=BrandDNATask,
    name="brand_dna.refresh_for_user",
)
def refresh_brand_dna_for_user_task(self: Task, user_id: str) -> dict[str, Any]:
    """Analyze successful generations and upsert BrandDNA for one seller."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_brand_dna_service(session)
            view = await service.refresh_from_successful_generations(
                user_id=UUID(user_id)
            )
            if view is None:
                return {"user_id": user_id, "status": "empty", "version": 0}
            logger.info(
                "BrandDNA refresh done user_id=%s status=%s version=%s",
                user_id,
                view.status.value,
                view.version,
            )
            return {
                "user_id": user_id,
                "status": view.status.value,
                "version": view.version,
                "sample_count": view.sample_count,
            }

    return _run_async(_task)


def enqueue_brand_dna_refresh(user_id: UUID) -> None:
    """Fire-and-forget BrandDNA refresh after a successful generation finalize."""

    try:
        celery_app.send_task(
            "brand_dna.refresh_for_user",
            kwargs={"user_id": str(user_id)},
        )
    except Exception:
        logger.warning(
            "Failed to enqueue BrandDNA refresh user_id=%s",
            user_id,
            exc_info=True,
        )
