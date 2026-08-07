"""Default adapters for ``AIEnginePort`` / ``ImagePipelinePort`` (A1)."""

from __future__ import annotations

from app.services import ai_engine as _ai_engine
from app.services.image_optimizer import (
    OptimizedImage,
    create_generation_thumbnail,
    optimize_image_lossless,
)


class FaceFixAdapter:
    """Delegates to the process-local FaceFix engine."""

    async def fix_if_needed(self, image_bytes: bytes) -> bytes:
        return await _ai_engine.get_face_fix_engine().fix_if_needed(image_bytes)


class ProviderHealthAdapter:
    """Delegates to Midjourney pool health counters."""

    async def note_success(self, provider_name: str) -> None:
        await _ai_engine.note_provider_success(provider_name)

    async def note_failure(self, provider_name: str) -> None:
        await _ai_engine.note_provider_failure(provider_name)


class DefaultAIEngineFacade:
    """Composition root façade satisfying ``AIEnginePort``."""

    def __init__(
        self,
        *,
        face_fix: FaceFixAdapter | None = None,
        provider_health: ProviderHealthAdapter | None = None,
    ) -> None:
        self._face_fix = face_fix or FaceFixAdapter()
        self._provider_health = provider_health or ProviderHealthAdapter()

    @property
    def face_fix(self) -> FaceFixAdapter:
        return self._face_fix

    @property
    def provider_health(self) -> ProviderHealthAdapter:
        return self._provider_health


class DefaultImagePipeline:
    """Composition root façade satisfying ``ImagePipelinePort``."""

    async def optimize_lossless(self, image_bytes: bytes) -> OptimizedImage:
        return await optimize_image_lossless(image_bytes)

    async def create_thumbnail(self, image_bytes: bytes) -> OptimizedImage:
        return await create_generation_thumbnail(image_bytes)


def build_default_ai_engine() -> DefaultAIEngineFacade:
    return DefaultAIEngineFacade()


def build_default_image_pipeline() -> DefaultImagePipeline:
    return DefaultImagePipeline()
