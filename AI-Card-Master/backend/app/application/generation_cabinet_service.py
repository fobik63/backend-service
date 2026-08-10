"""Application service: generation submit pipeline + cabinet queries.

Submit chain: validate options → validate image → upload → enqueue job → result.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from app.application.generation_errors import (
    GenerationInternalError,
    GenerationNotFoundError,
    GenerationPaymentRequiredError,
    GenerationStorageUnavailableError,
    GenerationSubmissionError,
)
from app.application.generation_image_validation import (
    read_bounded_bytes,
    validate_image,
)
from app.application.generation_options import (
    cost_for_mode,
    effective_engine_mode,
    ensure_generation_options_allowed,
    validate_owned_source_object_key,
)
from app.application.ports.persistence import GenerationRepositoryPort
from app.core.config import get_settings
from app.domain.brand_dna import (
    apply_brand_dna_to_prompt,
    apply_brand_dna_to_style,
)
from app.domain.brand_lora import (
    apply_brand_filter_to_prompt,
    apply_brand_filter_to_style,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
    MarketplaceTextContent,
    SlideStatus,
)
from app.domain.source_retention import SourceRetentionStatus
from app.infrastructure.brand_dna_factory import build_brand_dna_service
from app.infrastructure.brand_lora_factory import build_brand_lora_service
from app.infrastructure.generation_history_cache import (
    get_cached_generation_history,
    get_cached_generation_status,
    invalidate_generation_history_cache,
    set_cached_generation_history,
    set_cached_generation_status,
)
from app.models.user import User
from app.schemas.generations import (
    GenerationCreateResponse,
    GenerationErrorResponse,
    GenerationHistoryItemResponse,
    GenerationSlideResponse,
    GenerationStatusResponse,
    MarketplaceTextResponse,
    ModelModeRequest,
)
from app.services.billing_service import BillingValidationError
from app.services.model_vto import (
    MODEL_VTO_PRODUCT_CATEGORY,
    ModelTypage,
    build_model_vto_task,
)
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
    get_s3_storage,
)
from app.services.series_generator import SeriesTask, build_series_tasks_cached

logger = logging.getLogger(__name__)

STATUS_URL_TEMPLATE = "/api/v1/generations/{task_id}"


@dataclass(frozen=True, slots=True)
class GenerationCreateResult:
    task_id: UUID
    status: GenerationJobStatus
    idempotent_replay: bool

    def to_response(self) -> GenerationCreateResponse:
        return GenerationCreateResponse(
            task_id=self.task_id,
            status=self.status,
            status_url=STATUS_URL_TEMPLATE.format(task_id=self.task_id),
            idempotent_replay=self.idempotent_replay,
        )


class GenerationCabinetService:
    """Orchestrates generation submit and cabinet read models."""

    def __init__(
        self,
        repository: GenerationRepositoryPort,
        db_session: Any,
    ) -> None:
        self._repository = repository
        self._db_session = db_session

    # ── Submit pipeline ─────────────────────────────────────────────────

    async def submit_from_upload(
        self,
        *,
        user: User,
        image_bytes: bytes,
        claimed_content_type: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        overlay_texts: Mapping[str, str],
        idempotency_key: str | None,
        mask_bytes: bytes | None = None,
        mask_content_type: str | None = None,
        preserve_subject: bool = True,
        editor_cover_only: bool = False,
        style_prompt: str | None = None,
    ) -> GenerationCreateResult:
        """Receive bytes → validate → S3 → durable job → response DTO."""

        settings = get_settings()
        resolved_engine = effective_engine_mode(engine_mode, post_processing_mode)
        ensure_generation_options_allowed(
            resolved_engine, post_processing_mode, user
        )

        if idempotency_key:
            idempotency_key = idempotency_key.strip()
            existing = await self._repository.find_idempotent_job(
                user_id=user.id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return GenerationCreateResult(
                    task_id=existing.id,
                    status=GenerationJobStatus(existing.status),
                    idempotent_replay=True,
                )

        generation_cost = cost_for_mode(post_processing_mode)
        if settings.generation_charge_coins and user.ai_coins < generation_cost:
            raise GenerationPaymentRequiredError("Insufficient AI-coin balance.")

        image_bytes = read_bounded_bytes(
            image_bytes, max_bytes=settings.generation_max_upload_bytes
        )
        mime_type, extension = await validate_image(
            image_bytes, claimed_content_type
        )

        mask_object_key: str | None = None
        validated_mask: bytes | None = None
        mask_mime = "image/png"
        if mask_bytes is not None:
            validated_mask = read_bounded_bytes(
                mask_bytes, max_bytes=settings.generation_max_upload_bytes
            )
            mask_mime, _mask_ext = await validate_image(
                validated_mask, mask_content_type
            )

        input_key = f"generation-inputs/{user.id}/{uuid4().hex}{extension}"
        storage = None
        uploaded_keys: list[str] = []
        try:
            storage = get_s3_storage()
            await storage.upload_bytes(
                object_key=input_key,
                data=image_bytes,
                content_type=mime_type,
                presign=False,
            )
            uploaded_keys.append(input_key)

            if validated_mask is not None:
                from app.services.product_compositor import companion_mask_object_key

                mask_object_key = companion_mask_object_key(input_key)
                await storage.upload_bytes(
                    object_key=mask_object_key,
                    data=validated_mask,
                    content_type=mask_mime,
                    presign=False,
                )
                uploaded_keys.append(mask_object_key)

            if editor_cover_only:
                from app.services.series_generator import build_editor_background_task

                slide_tasks = await self._slide_tasks_with_brand(
                    user_id=user.id,
                    slide_tasks=(
                        build_editor_background_task(style_prompt=style_prompt),
                    ),
                )
            else:
                slide_tasks = await self._slide_tasks_with_brand(
                    user_id=user.id,
                    slide_tasks=await build_series_tasks_cached(product_category),
                )
            job, created = await self._repository.create_job(
                user_id=user.id,
                idempotency_key=idempotency_key,
                subscription_status=user.subscription_status.value,
                engine_mode=resolved_engine,
                post_processing_mode=post_processing_mode,
                input_object_key=input_key,
                product_category=product_category,
                apply_text_overlays=apply_text_overlays,
                overlay_texts=overlay_texts,
                slide_tasks=slide_tasks,
                mask_object_key=mask_object_key,
                preserve_subject=preserve_subject,
            )
            if not created:
                for key in uploaded_keys:
                    await self._best_effort_delete(storage, key)
            if created:
                await invalidate_generation_history_cache(user.id)
            return GenerationCreateResult(
                task_id=job.id,
                status=GenerationJobStatus(job.status),
                idempotent_replay=not created,
            )
        except BillingValidationError as exc:
            for key in uploaded_keys:
                if storage is not None:
                    await self._best_effort_delete(storage, key)
            raise GenerationPaymentRequiredError(str(exc)) from exc
        except S3StorageConfigurationError as exc:
            raise GenerationStorageUnavailableError(
                "Object storage is not configured."
            ) from exc
        except S3StorageError as exc:
            logger.exception(
                "Generation input upload failed user_id=%s", user.id
            )
            for key in uploaded_keys:
                if storage is not None:
                    await self._best_effort_delete(storage, key)
            raise GenerationStorageUnavailableError(
                "Object storage is temporarily unavailable."
            ) from exc
        except GenerationSubmissionError:
            for key in uploaded_keys:
                if storage is not None:
                    await self._best_effort_delete(storage, key)
            raise
        except Exception as exc:
            for key in uploaded_keys:
                if storage is not None:
                    await self._best_effort_delete(storage, key)
            logger.exception(
                "Could not create durable generation job user_id=%s", user.id
            )
            raise GenerationInternalError(
                "Failed to create generation task."
            ) from exc

    async def submit_model_mode(
        self,
        *,
        user: User,
        payload: ModelModeRequest,
        idempotency_key: str | None,
    ) -> GenerationCreateResult:
        """Validate model VTO request → durable job → response DTO."""

        settings = get_settings()
        validate_owned_source_object_key(payload.source_image_object_key, user.id)
        resolved_engine = effective_engine_mode(
            payload.engine_mode, payload.post_processing_mode
        )
        ensure_generation_options_allowed(
            resolved_engine, payload.post_processing_mode, user
        )

        if idempotency_key:
            idempotency_key = idempotency_key.strip()
            existing = await self._repository.find_idempotent_job(
                user_id=user.id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return GenerationCreateResult(
                    task_id=existing.id,
                    status=GenerationJobStatus(existing.status),
                    idempotent_replay=True,
                )

        generation_cost = cost_for_mode(payload.post_processing_mode)
        if settings.generation_charge_coins and user.ai_coins < generation_cost:
            raise GenerationPaymentRequiredError("Insufficient AI-coin balance.")

        task = build_model_vto_task(
            typage=ModelTypage(
                height_cm=payload.height_cm,
                body_type=payload.body_type,
                ethnicity=payload.ethnicity,
            ),
            background=payload.background,
            pose=payload.pose,
        )
        slide_tasks = await self._slide_tasks_with_brand(
            user_id=user.id, slide_tasks=(task,)
        )
        try:
            job, created = await self._repository.create_job(
                user_id=user.id,
                idempotency_key=idempotency_key,
                subscription_status=user.subscription_status.value,
                engine_mode=resolved_engine,
                post_processing_mode=payload.post_processing_mode,
                input_object_key=payload.source_image_object_key,
                product_category=MODEL_VTO_PRODUCT_CATEGORY,
                apply_text_overlays=False,
                overlay_texts={},
                slide_tasks=slide_tasks,
            )
            if created:
                await invalidate_generation_history_cache(user.id)
            return GenerationCreateResult(
                task_id=job.id,
                status=GenerationJobStatus(job.status),
                idempotent_replay=not created,
            )
        except BillingValidationError as exc:
            raise GenerationPaymentRequiredError(str(exc)) from exc
        except GenerationSubmissionError:
            raise
        except Exception as exc:
            logger.exception(
                "Could not create durable model generation job user_id=%s",
                user.id,
            )
            raise GenerationInternalError(
                "Failed to create model generation task."
            ) from exc

    # ── Cabinet reads ───────────────────────────────────────────────────

    async def get_status(
        self, *, user_id: UUID, task_id: UUID
    ) -> GenerationStatusResponse:
        cached = await get_cached_generation_status(user_id=user_id, task_id=task_id)
        if cached is not None:
            try:
                return GenerationStatusResponse.model_validate_json(
                    json.dumps(cached, ensure_ascii=False)
                )
            except (ValueError, TypeError):
                logger.debug("Generation status cache payload invalid", exc_info=True)

        job = await self._repository.get_detail_for_user(task_id, user_id)
        if job is None:
            raise GenerationNotFoundError("Generation task was not found.")

        storage = self._optional_storage()
        archive_url: str | None = None
        archive_status, _ = self._archive_access_state(job, datetime.now(UTC))
        if storage is not None and job.archive_object_key and archive_status == "available":
            try:
                archive_url = await storage.generate_presigned_url(
                    object_key=job.archive_object_key
                )
            except S3StorageError:
                logger.warning(
                    "Could not presign archive for job %s", job.id, exc_info=True
                )

        slides: list[GenerationSlideResponse] = []
        for slide in job.slides:
            result_url: str | None = None
            if storage is not None and slide.result_object_key:
                try:
                    result_url = await storage.generate_presigned_url(
                        object_key=slide.result_object_key
                    )
                except S3StorageError:
                    logger.warning(
                        "Could not presign slide %s for job %s",
                        slide.id,
                        job.id,
                        exc_info=True,
                    )
            slide_error = None
            if slide.error_code and slide.error_message:
                slide_error = GenerationErrorResponse(
                    code=slide.error_code,
                    message=slide.error_message,
                    retryable=slide.error_retryable,
                )
            slides.append(
                GenerationSlideResponse(
                    slide_key=slide.slide_key,
                    position=slide.position,
                    status=SlideStatus(slide.status),
                    progress=slide.progress,
                    provider_used=slide.provider_used,
                    result_url=result_url,
                    warning=slide.warning,
                    error=slide_error,
                )
            )

        job_error = None
        if job.error_code and job.error_message:
            job_error = GenerationErrorResponse(
                code=job.error_code,
                message=job.error_message,
                retryable=job.error_retryable,
            )
        response = GenerationStatusResponse(
            task_id=job.id,
            status=GenerationJobStatus(job.status),
            progress=job.progress,
            provider_used=job.provider_used,
            warning=job.warning,
            archive_url=archive_url,
            marketplace_text=self._marketplace_text_response(
                getattr(job, "marketplace_text", None)
            ),
            slides=tuple(slides),
            error=job_error,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )
        await set_cached_generation_status(
            user_id=user_id,
            task_id=task_id,
            payload=response.model_dump(mode="json"),
            terminal=response.status
            in (GenerationJobStatus.COMPLETED, GenerationJobStatus.FAILED),
        )
        return response

    async def list_history(
        self,
        *,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[GenerationHistoryItemResponse]:
        cached_items = await get_cached_generation_history(
            user_id=user_id, limit=limit, offset=offset
        )
        if cached_items is not None:
            try:
                return [
                    GenerationHistoryItemResponse.model_validate_json(
                        json.dumps(item, ensure_ascii=False)
                    )
                    for item in cached_items
                ]
            except (ValueError, TypeError):
                logger.debug(
                    "Generation history cache payload invalid", exc_info=True
                )

        summaries = await self._repository.list_summary_for_user(
            user_id=user_id, limit=limit, offset=offset
        )
        storage = self._optional_storage()
        now = datetime.now(UTC)
        response: list[GenerationHistoryItemResponse] = []
        for summary in summaries:
            job = summary.job
            thumbnail_url: str | None = None
            thumbnail_key = job.thumbnail_object_key
            thumbnail_mime = job.thumbnail_mime_type
            thumbnail_size = job.thumbnail_size_bytes
            if not thumbnail_key and job.slides:
                cover = next(
                    (slide for slide in job.slides if slide.slide_key == "cover"),
                    job.slides[0],
                )
                thumbnail_key = cover.result_object_key
                thumbnail_mime = thumbnail_mime or cover.result_mime_type
            if storage is not None and thumbnail_key:
                try:
                    thumbnail_url = await storage.generate_presigned_url(
                        object_key=thumbnail_key
                    )
                except S3StorageError:
                    logger.warning(
                        "Could not presign thumbnail for job %s",
                        job.id,
                        exc_info=True,
                    )

            archive_url: str | None = None
            archive_status, archive_expires_at = self._archive_access_state(job, now)
            if (
                archive_status == "available"
                and storage is not None
                and job.archive_object_key
            ):
                try:
                    archive_url = await storage.generate_presigned_url(
                        object_key=job.archive_object_key
                    )
                except S3StorageError:
                    logger.warning(
                        "Could not presign archive for job %s",
                        job.id,
                        exc_info=True,
                    )
                    archive_status = "unavailable"

            response.append(
                GenerationHistoryItemResponse(
                    task_id=job.id,
                    status=GenerationJobStatus(job.status),
                    progress=job.progress,
                    product_category=job.product_category,
                    slide_count=summary.slide_count,
                    thumbnail_url=thumbnail_url,
                    thumbnail_mime_type=thumbnail_mime,
                    thumbnail_size_bytes=thumbnail_size,
                    archive_status=archive_status,
                    archive_url=archive_url,
                    archive_expires_at=(
                        archive_expires_at.isoformat() if archive_expires_at else None
                    ),
                    provider_used=job.provider_used,
                    warning=job.warning,
                    created_at=job.created_at.isoformat(),
                    completed_at=(
                        job.completed_at.isoformat() if job.completed_at else None
                    ),
                )
            )
        await set_cached_generation_history(
            user_id=user_id,
            limit=limit,
            offset=offset,
            items=[item.model_dump(mode="json") for item in response],
        )
        return response

    # ── Internals ───────────────────────────────────────────────────────

    async def _slide_tasks_with_brand(
        self,
        *,
        user_id: UUID,
        slide_tasks: tuple[SeriesTask, ...] | list[SeriesTask] | Sequence[SeriesTask],
    ) -> tuple[SeriesTask, ...]:
        try:
            brand_filter = await build_brand_lora_service(
                self._db_session
            ).get_active_filter(user_id=user_id)
        except Exception:
            logger.warning(
                "Active Brand LoRA lookup failed user_id=%s; continuing without filter",
                user_id,
                exc_info=True,
            )
            brand_filter = None

        try:
            brand_dna = await build_brand_dna_service(
                self._db_session
            ).get_active_context(user_id=user_id)
        except Exception:
            logger.warning(
                "Active BrandDNA lookup failed user_id=%s; continuing without DNA",
                user_id,
                exc_info=True,
            )
            brand_dna = None

        if brand_filter is None and brand_dna is None:
            return tuple(slide_tasks)

        patched: list[SeriesTask] = []
        for task in slide_tasks:
            style = task.selected_style
            text = task.user_text
            if brand_filter is not None:
                style = apply_brand_filter_to_style(style, brand_filter)
                text = apply_brand_filter_to_prompt(text, brand_filter)
            if brand_dna is not None:
                style = apply_brand_dna_to_style(style, brand_dna)
                text = apply_brand_dna_to_prompt(text, brand_dna)
            patched.append(
                SeriesTask(
                    slide_key=task.slide_key,
                    selected_style=style,
                    user_text=text,
                )
            )
        return tuple(patched)

    @staticmethod
    async def _best_effort_delete(storage: Any, object_key: str) -> None:
        try:
            await storage.delete_object(object_key=object_key)
        except S3StorageError:
            logger.warning(
                "Could not clean up orphan input %s", object_key, exc_info=True
            )

    @staticmethod
    def _optional_storage() -> Any | None:
        try:
            return get_s3_storage()
        except S3StorageError:
            logger.warning("S3 unavailable while building generation response", exc_info=True)
            return None

    @staticmethod
    def _marketplace_text_response(value: object) -> MarketplaceTextResponse | None:
        if not value:
            return None
        if isinstance(value, MarketplaceTextContent):
            return MarketplaceTextResponse.from_domain(value)
        if isinstance(value, dict):
            return MarketplaceTextResponse.from_domain(
                MarketplaceTextContent.model_validate(value)
            )
        return None

    @staticmethod
    def _archive_retention() -> timedelta:
        return timedelta(hours=get_settings().source_retention_hours)

    @classmethod
    def _archive_access_state(
        cls,
        job: Any,
        now: datetime,
    ) -> tuple[
        Literal["available", "expired", "pending", "unavailable", "deleted"],
        datetime | None,
    ]:
        retention_status = getattr(job, "archive_retention_status", None)
        if retention_status == SourceRetentionStatus.DELETED.value:
            return "deleted", None

        if not job.archive_object_key:
            if job.status in (
                GenerationJobStatus.FAILED.value,
                GenerationJobStatus.COMPLETED.value,
            ):
                return "unavailable", None
            return "pending", None
        if job.completed_at is None:
            return "pending", None

        expires_at = cls._to_utc(job.completed_at) + cls._archive_retention()
        if cls._to_utc(now) < expires_at:
            return "available", expires_at
        return "expired", expires_at

    @staticmethod
    def _to_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
