"""Celery tasks for competitor-link deep scrape + Claude deep analysis (§77–78)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.domain.competitor_audit import (
    CompetitorAuditPermanentError,
    CompetitorAuditTransientError,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.competitor_audit_factory import build_competitor_audit_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CompetitorAuditTask(Task):
    """Retry policy for marketplace captcha / timeout failures."""

    autoretry_for = (CompetitorAuditTransientError, SoftTimeLimitExceeded)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


class CompetitorDeepAnalysisTask(Task):
    """Retry policy for transient Claude / image-fetch failures."""

    autoretry_for = (SoftTimeLimitExceeded,)
    retry_backoff = True
    retry_backoff_max = 180
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


@celery_app.task(
    bind=True,
    base=CompetitorAuditTask,
    name="analytics.run_competitor_audit",
    soft_time_limit=600,
    time_limit=660,
)
def run_competitor_audit_task(self: Task, job_id: str) -> dict[str, Any]:
    """Deep-scrape ≤3 competitor links, then enqueue Claude deep analysis."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_competitor_audit_service(
                session,
                enqueue_analysis=True,
                require_claude_client=False,
            )
            try:
                job = await service.run_scrape(job_id=UUID(job_id))
            except CompetitorAuditTransientError:
                raise
            except CompetitorAuditPermanentError as exc:
                logger.warning(
                    "Competitor audit permanent failure job_id=%s: %s",
                    job_id,
                    exc,
                )
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(exc)[:500],
                }
            finally:
                await service.aclose()

            card_count = 0
            if job.result_payload and isinstance(job.result_payload.get("cards"), list):
                card_count = len(job.result_payload["cards"])
            logger.info(
                "Competitor scrape finished job_id=%s status=%s cards=%s",
                job.id,
                job.status.value,
                card_count,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "card_count": card_count,
            }

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=CompetitorDeepAnalysisTask,
    name="claude.run_competitor_deep_analysis",
    soft_time_limit=720,
    time_limit=780,
)
def run_competitor_deep_analysis_task(self: Task, job_id: str) -> dict[str, Any]:
    """Claude 4.7 Opus Vision + reviews → competitor_weaknesses / blueprint JSON."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_competitor_audit_service(
                session,
                enqueue_analysis=False,
                require_claude_client=False,
                with_scraper=False,
            )
            try:
                job = await service.run_deep_analysis(job_id=UUID(job_id))
            except CompetitorAuditPermanentError as exc:
                logger.warning(
                    "Competitor deep analysis permanent failure job_id=%s: %s",
                    job_id,
                    exc,
                )
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(exc)[:500],
                }
            finally:
                await service.aclose()

            insufficient = False
            card_count = 0
            if job.analysis_payload:
                insufficient = bool(job.analysis_payload.get("insufficient_data"))
                cards = job.analysis_payload.get("cards")
                if isinstance(cards, list):
                    card_count = len(cards)
            logger.info(
                "Competitor deep analysis finished job_id=%s status=%s "
                "cards=%s insufficient_data=%s",
                job.id,
                job.status.value,
                card_count,
                insufficient,
            )
            return {
                "job_id": str(job.id),
                "status": job.status.value,
                "card_count": card_count,
                "insufficient_data": insufficient,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
            }

    return _run_async(_task)
