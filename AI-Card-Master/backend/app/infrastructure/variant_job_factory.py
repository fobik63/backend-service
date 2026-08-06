"""Adapter that creates generation jobs for Smart Variant Sync color items."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.services.series_generator import build_series_tasks_cached


class VariantGenerationJobFactory:
    """Wraps GenerationRepository.create_job for the variant recolor worker."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = GenerationRepository(session)

    async def create_for_variant_item(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        input_object_key: str,
        product_category: str | None,
        apply_text_overlays: bool,
        overlay_texts: dict[str, str],
        idempotency_key: str,
    ) -> UUID:
        job, _created = await self._repository.create_job(
            user_id=user_id,
            idempotency_key=idempotency_key,
            subscription_status=subscription_status,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            input_object_key=input_object_key,
            product_category=product_category,
            apply_text_overlays=apply_text_overlays,
            overlay_texts=overlay_texts,
            slide_tasks=await build_series_tasks_cached(product_category),
        )
        return job.id
