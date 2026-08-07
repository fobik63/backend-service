"""Composition root helpers for Bulk Generation (API + Celery)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.bulk_generation_service import BulkGenerationService
from app.core.config import get_settings
from app.core.pricing import generation_cost_for_mode
from app.infrastructure.bulk_job_factory import GenerationRepositoryJobFactory
from app.infrastructure.persistence.bulk_generation_repository import (
    BulkGenerationRepository,
)
from app.services.push_notifier import InAppPushNotifier
from app.services.s3_storage import get_s3_storage
from app.services.telegram_user_notify import TelegramUserNotifier


def build_bulk_generation_service(
    db_session: AsyncSession,
    *,
    coins_per_product: int | None = None,
) -> BulkGenerationService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    return BulkGenerationService(
        BulkGenerationRepository(db_session),
        storage=get_s3_storage(),
        job_factory=GenerationRepositoryJobFactory(db_session),
        max_products=settings.bulk_generation_max_products,
        max_zip_bytes=settings.bulk_generation_max_zip_bytes,
        max_image_bytes=settings.generation_max_upload_bytes,
        coins_per_product=coins_per_product
        if coins_per_product is not None
        else generation_cost_for_mode("fast"),
        charge_coins=settings.generation_charge_coins,
        telegram=TelegramUserNotifier(),
        push=InAppPushNotifier(db_session),
    )
