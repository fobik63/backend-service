"""Celery tasks for Churn Prevention inactivity scans and style-update Telegram."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from celery import Task

from app.application.winback_service import WinbackService
from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.persistence.winback_repository import WinbackRepository
from app.models.database import SessionLocal
from app.services.telegram_user_notify import TelegramUserNotifier
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


class WinbackTask(Task):
    """Retry policy for idempotent win-back scanners."""

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


def _build_service(session: Any) -> WinbackService:
    settings = get_settings()
    return WinbackService(
        WinbackRepository(session),
        inactivity_days=settings.winback_inactivity_days,
        free_generations=settings.winback_free_generations,
        discount_percent=settings.winback_discount_percent,
        offer_ttl_hours=settings.winback_offer_ttl_hours,
        telegram=TelegramUserNotifier(),
    )


@celery_app.task(
    bind=True,
    base=WinbackTask,
    name="winback.scan_inactivity",
)
def scan_inactivity_task(self: Task) -> dict[str, int]:
    """Create one-shot offers for users inactive longer than the configured window."""

    async def _task() -> dict[str, int]:
        async with SessionLocal() as session:
            service = _build_service(session)
            result = await service.process_inactivity_batch(limit=100)
            logger.info("Win-back inactivity scan: %s", result)
            return result

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=WinbackTask,
    name="winback.notify_luxury_loft_updates",
)
def notify_luxury_loft_updates_task(self: Task) -> dict[str, int]:
    """Telegram trigger: favorite style Luxury Loft received an update."""

    async def _task() -> dict[str, int]:
        settings = get_settings()
        campaign_key = settings.winback_style_campaign_key.strip() or (
            f"luxury_loft_{datetime.now(UTC).date().isoformat()}"
        )
        async with SessionLocal() as session:
            service = _build_service(session)
            result = await service.notify_luxury_loft_updates(
                campaign_key=campaign_key,
                limit=200,
            )
            logger.info("Win-back Luxury Loft notify: %s", result)
            return result

    return _run_async(_task)
