"""Use cases for Claude 4.7 Vision & Chain-of-Thought competitor analysis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.application.ports.claude_reasoning import (
    ClaudeReasoningPersistencePort,
    ClaudeVisionReasoningPort,
)
from app.domain.bulk_generation import detect_image_mime
from app.domain.claude_reasoning import (
    ClaudeReasoningJobStatus,
    ClaudeReasoningJobView,
    CompetitorTextContext,
    merge_chain_of_thought,
    redis_stage_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class ObjectStoragePort(Protocol):
    """Minimal S3 port for competitor image download."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> object: ...

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...


class ClaudeReasoningError(Exception):
    """Base Claude reasoning workflow failure."""


class ClaudeReasoningValidationError(ClaudeReasoningError):
    """Invalid request payload or images."""


class ClaudeReasoningNotFoundError(ClaudeReasoningError):
    """Job was not found for the user."""


class ClaudeReasoningService:
    """Coordinate enqueue → Vision CoT → text alignment via Celery workers."""

    def __init__(
        self,
        repository: ClaudeReasoningPersistencePort,
        *,
        storage: ObjectStoragePort,
        model_name: str,
        max_images: int,
        max_image_bytes: int,
        redis_stage_ttl_seconds: int,
        claude: ClaudeVisionReasoningPort | None = None,
    ) -> None:
        if not model_name.strip():
            raise ClaudeReasoningValidationError("model_name must not be empty.")
        if max_images <= 0:
            raise ClaudeReasoningValidationError("max_images must be positive.")
        if max_image_bytes <= 0:
            raise ClaudeReasoningValidationError("max_image_bytes must be positive.")
        if redis_stage_ttl_seconds <= 0:
            raise ClaudeReasoningValidationError(
                "redis_stage_ttl_seconds must be positive."
            )
        self._repository = repository
        self._claude = claude
        self._storage = storage
        self._model_name = model_name.strip()
        self._max_images = max_images
        self._max_image_bytes = max_image_bytes
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds

    def _require_claude(self) -> ClaudeVisionReasoningPort:
        if self._claude is None:
            raise ClaudeReasoningError(
                "Claude Vision client is not configured for this process."
            )
        return self._claude

    async def enqueue_analysis(
        self,
        *,
        user_id: UUID,
        images: tuple[bytes, ...],
        text_context: CompetitorTextContext,
        idempotency_key: str | None = None,
    ) -> tuple[ClaudeReasoningJobView, bool]:
        """Upload images, create a queued job; caller enqueues Celery.

        Returns (job, idempotent_replay).
        """

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        if not images:
            raise ClaudeReasoningValidationError(
                "At least one competitor image is required."
            )
        if len(images) > self._max_images:
            raise ClaudeReasoningValidationError(
                f"Maximum {self._max_images} images allowed per request."
            )

        object_keys: list[str] = []
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        for index, payload in enumerate(images):
            if len(payload) > self._max_image_bytes:
                raise ClaudeReasoningValidationError(
                    f"Image #{index + 1} exceeds size limit."
                )
            detected = detect_image_mime(payload)
            if detected is None:
                raise ClaudeReasoningValidationError(
                    f"Image #{index + 1} must be JPEG, PNG, or WebP."
                )
            mime_type, extension = detected
            object_key = (
                f"claude-reasoning/{user_id}/{stamp}_{index:02d}{extension}"
            )
            await self._storage.upload_bytes(
                object_key=object_key,
                data=payload,
                content_type=mime_type,
                presign=False,
            )
            object_keys.append(object_key)

        job = await self._repository.create_job(
            user_id=user_id,
            image_object_keys=tuple(object_keys),
            text_context=text_context.model_dump(mode="json"),
            model_name=self._model_name,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> ClaudeReasoningJobView:
        """Store Celery task id after queue publish."""

        return await self._repository.mark_status(
            job_id=job_id,
            status=ClaudeReasoningJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> ClaudeReasoningJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise ClaudeReasoningNotFoundError("Claude reasoning job not found.")
        return job

    async def run_chain_of_thought(self, *, job_id: UUID) -> ClaudeReasoningJobView:
        """Execute Vision → Reasoning CoT for a queued job (Celery worker)."""

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise ClaudeReasoningNotFoundError("Claude reasoning job not found.")
        if job.status == ClaudeReasoningJobStatus.COMPLETED and job.final_result:
            return job
        if job.status == ClaudeReasoningJobStatus.FAILED:
            raise ClaudeReasoningError(
                job.error_message or "Claude reasoning job previously failed."
            )

        try:
            await self._repository.mark_status(
                job_id=job_id,
                status=ClaudeReasoningJobStatus.VISION_RUNNING,
            )
            text_context = CompetitorTextContext.model_validate(job.text_context)

            from app.domain.claude_reasoning import VisionStageResult

            vision: VisionStageResult | None = None
            cached_vision = await self._read_stage_cache(job_id, "vision")
            if cached_vision is not None:
                vision = VisionStageResult.model_validate(cached_vision)
            elif job.vision_result is not None:
                vision = VisionStageResult.model_validate(job.vision_result)

            claude = self._require_claude()
            if vision is None:
                images = await self._load_images(job.image_object_keys)
                vision, in_tok, out_tok = await claude.analyze_visual_triggers(
                    images=images,
                    product_category=text_context.product_category,
                )
                vision_payload = vision.model_dump(mode="json")
                await self._write_stage_cache(job_id, "vision", vision_payload)
                await self._repository.save_vision_result(
                    job_id=job_id,
                    vision_result=vision_payload,
                    input_tokens_delta=in_tok,
                    output_tokens_delta=out_tok,
                )
            else:
                await self._repository.mark_status(
                    job_id=job_id,
                    status=ClaudeReasoningJobStatus.REASONING_RUNNING,
                )

            reasoning, in_tok2, out_tok2 = await claude.align_triggers_with_text(
                vision=vision,
                text_context=text_context,
            )
            reasoning_payload = reasoning.model_dump(mode="json")
            await self._write_stage_cache(job_id, "reasoning", reasoning_payload)

            final = merge_chain_of_thought(
                vision=vision,
                reasoning=reasoning,
                model_name=job.model_name,
            )
            final_payload = final.model_dump(mode="json")
            await self._write_stage_cache(job_id, "final", final_payload)

            return await self._repository.save_final_result(
                job_id=job_id,
                reasoning_result=reasoning_payload,
                final_result=final_payload,
                input_tokens_delta=in_tok2,
                output_tokens_delta=out_tok2,
            )
        except ClaudeReasoningError:
            raise
        except Exception as exc:
            logger.exception("Claude CoT failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=ClaudeReasoningJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise ClaudeReasoningError(str(exc)) from exc

    async def _load_images(
        self, object_keys: tuple[str, ...]
    ) -> tuple[tuple[bytes, str], ...]:
        loaded: list[tuple[bytes, str]] = []
        for key in object_keys:
            data = await self._storage.download_bytes(
                object_key=key,
                max_bytes=self._max_image_bytes,
            )
            detected = detect_image_mime(data)
            if detected is None:
                raise ClaudeReasoningValidationError(
                    f"Stored image is not a supported format: {key}"
                )
            mime_type, _ext = detected
            loaded.append((data, mime_type))
        return tuple(loaded)

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict
    ) -> None:
        try:
            await cache_json(
                redis_stage_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped Claude stage cache job_id=%s stage=%s",
                job_id,
                stage,
            )

    async def _read_stage_cache(self, job_id: UUID, stage: str) -> dict | None:
        try:
            return await get_cached_json(redis_stage_key(job_id, stage))
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; Claude stage cache miss job_id=%s stage=%s",
                job_id,
                stage,
            )
            return None
