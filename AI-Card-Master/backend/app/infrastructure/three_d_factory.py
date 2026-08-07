"""Composition root for 3D generation (API + Celery + WebSocket)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.three_d_service import ThreeDService
from app.core.config import get_settings
from app.infrastructure.persistence.three_d_repository import ThreeDRepository
from app.infrastructure.three_d_progress_cache import RedisThreeDProgressCache
from app.services.three_d.factory import ThreeDEngineFactory
from app.services.three_d.storage import get_three_d_object_storage


def build_three_d_service(db_session: AsyncSession) -> ThreeDService:
    """Wire ports for HTTP handlers, WebSocket, and Celery workers."""

    settings = get_settings()
    return ThreeDService(
        ThreeDRepository(db_session),
        engine=ThreeDEngineFactory.create(settings),
        storage=get_three_d_object_storage(),
        progress_cache=RedisThreeDProgressCache(
            ttl_seconds=settings.three_d_progress_ttl_seconds
        ),
        provider_name=settings.three_d_provider,
        cost_coins=settings.three_d_cost_coins,
        charge_coins=settings.generation_charge_coins,
        delivery_mode=settings.three_d_delivery_mode,
        poll_interval_seconds=settings.three_d_poll_interval_seconds,
        task_timeout_seconds=settings.three_d_task_timeout_seconds,
        max_download_bytes=settings.three_d_max_download_bytes,
        webhook_secret=settings.three_d_webhook_secret.get_secret_value(),
        progress_ttl_seconds=settings.three_d_progress_ttl_seconds,
        gpu_rental_provider_name=settings.three_d_gpu_rental_provider,
        gpu_rental_instance_type=settings.three_d_gpu_rental_instance_type,
        gpu_rental_coins_per_minute=settings.three_d_gpu_rental_coins_per_minute,
    )
