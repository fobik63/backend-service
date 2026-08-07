"""Application façade for generation cabinet HTTP endpoints (audit A2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.application.ports.persistence import GenerationRepositoryPort
from app.domain.generation import (
    GenerationEngineMode,
    GenerationPostProcessingMode,
)
from app.models.enums import SubscriptionStatus
from app.services.series_generator import SeriesTask


class GenerationCabinetService:
    """Thin application API over ``GenerationRepositoryPort`` for routers."""

    def __init__(self, repository: GenerationRepositoryPort) -> None:
        self._repository = repository

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ):
        return await self._repository.find_idempotent_job(
            user_id=user_id, idempotency_key=idempotency_key
        )

    async def create_job(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        subscription_status: SubscriptionStatus,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        input_object_key: str,
        product_category: str | None,
        apply_text_overlays: bool,
        overlay_texts: Mapping[str, str],
        slide_tasks: Sequence[SeriesTask],
    ):
        return await self._repository.create_job(
            user_id=user_id,
            idempotency_key=idempotency_key,
            subscription_status=subscription_status,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            input_object_key=input_object_key,
            product_category=product_category,
            apply_text_overlays=apply_text_overlays,
            overlay_texts=overlay_texts,
            slide_tasks=slide_tasks,
        )

    async def list_summary_for_user(self, *args, **kwargs):
        return await self._repository.list_summary_for_user(*args, **kwargs)

    async def get_detail_for_user(self, *args, **kwargs):
        return await self._repository.get_detail_for_user(*args, **kwargs)
