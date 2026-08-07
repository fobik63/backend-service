"""Celery tasks for Automated A/B Testing Logic."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.infrastructure.ab_test_factory import build_ab_test_service
from app.infrastructure.celery_app import celery_app
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AbTestTask(Task):
    """Retry policy for idempotent A/B generate / poll tasks."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


@celery_app.task(
    bind=True,
    base=AbTestTask,
    name="ab_test.generate_and_publish",
)
def generate_and_publish_task(self: Task, experiment_id: str) -> dict[str, Any]:
    """Generate 3 hypotheses and publish creatives to the ads cabinet."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            try:
                service = build_ab_test_service(
                    session,
                    require_claude_client=True,
                )
            except Exception:
                logger.warning(
                    "A/B Claude client unavailable; deterministic mode experiment_id=%s",
                    experiment_id,
                )
                service = build_ab_test_service(
                    session,
                    require_claude_client=False,
                )

            experiment = await service.run_generate_and_publish(
                experiment_id=UUID(experiment_id)
            )
            logger.info(
                "A/B generate/publish finished experiment_id=%s status=%s variants=%s",
                experiment.id,
                experiment.status.value,
                len(experiment.variants),
            )
            return {
                "experiment_id": str(experiment.id),
                "status": experiment.status.value,
                "variant_count": len(experiment.variants),
                "measurement_ends_at": (
                    experiment.measurement_ends_at.isoformat()
                    if experiment.measurement_ends_at
                    else None
                ),
            }

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=AbTestTask,
    name="ab_test.poll_active_experiments",
)
def poll_active_experiments_task(self: Task) -> dict[str, int]:
    """Refresh CTR and auto-resolve experiments after the measurement window."""

    async def _task() -> dict[str, int]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_ab_test_service(session)
            result = await service.poll_active_experiments(
                limit=settings.ab_test_poll_batch_size,
            )
            logger.info("A/B poll active experiments: %s", result)
            return result

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=AbTestTask,
    name="ab_test.resolve_experiment",
)
def resolve_experiment_task(
    self: Task,
    experiment_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Manually or scheduled resolve: keep winner, delete losers."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_ab_test_service(session)
            experiment = await service.resolve_experiment(
                experiment_id=UUID(experiment_id),
                force=force,
            )
            winner = None
            if experiment.resolution_result:
                winner = experiment.resolution_result.get("winner_strategy")
            return {
                "experiment_id": str(experiment.id),
                "status": experiment.status.value,
                "winner_strategy": winner,
                "winner_variant_id": (
                    str(experiment.winner_variant_id)
                    if experiment.winner_variant_id
                    else None
                ),
            }

    return _run_async(_task)
