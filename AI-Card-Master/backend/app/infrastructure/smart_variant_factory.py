"""Composition root helpers for Smart Variant Sync (API + Celery)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.smart_variant_service import SmartVariantService
from app.core.config import get_settings
from app.core.pricing import generation_cost_for_mode
from app.domain.bulk_generation import PushNotificationPayload
from app.domain.smart_variant import VariantPushPayload
from app.infrastructure.fabric_recolor import StableDiffusionFabricRecolor
from app.infrastructure.persistence.smart_variant_repository import (
    SmartVariantRepository,
)
from app.infrastructure.variant_job_factory import VariantGenerationJobFactory
from app.services.push_notifier import InAppPushNotifier
from app.services.s3_storage import get_s3_storage
from app.services.telegram_user_notify import TelegramUserNotifier


class _VariantPushBridge:
    """Adapt VariantPushPayload → InAppPushNotifier (bulk payload shape)."""

    def __init__(self, session: AsyncSession) -> None:
        self._inner = InAppPushNotifier(session)

    async def send(
        self,
        *,
        user_id,
        payload: VariantPushPayload,
    ) -> bool:
        return await self._inner.send(
            user_id=user_id,
            payload=PushNotificationPayload(
                title=payload.title,
                body=payload.body,
                data=payload.data,
            ),
        )


def build_smart_variant_service(
    db_session: AsyncSession,
    *,
    coins_per_color: int | None = None,
) -> SmartVariantService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    return SmartVariantService(
        SmartVariantRepository(db_session),
        storage=get_s3_storage(),
        recolor=StableDiffusionFabricRecolor(),
        job_factory=VariantGenerationJobFactory(db_session),
        max_colors=settings.smart_variant_max_colors,
        max_image_bytes=settings.generation_max_upload_bytes,
        coins_per_color=coins_per_color
        if coins_per_color is not None
        else generation_cost_for_mode("fast"),
        charge_coins=settings.generation_charge_coins,
        telegram=TelegramUserNotifier(),
        push=_VariantPushBridge(db_session),
    )
