"""Fast generation API backed by PostgreSQL, Celery, Redis, and S3."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.core.config import get_settings
from app.domain.generation import GenerationJobStatus, MarketplaceTextContent, SlideStatus
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.infrastructure.generation_history_cache import (
    get_cached_generation_history,
    invalidate_generation_history_cache,
    set_cached_generation_history,
)
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.model_vto import (
    MODEL_VTO_PRODUCT_CATEGORY,
    BodyType,
    Ethnicity,
    ModelTypage,
    build_model_vto_task,
)
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
    get_s3_storage,
)
from app.services.series_generator import build_series_tasks_cached

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/generations", tags=["generations"])
_ARCHIVE_RETENTION = timedelta(hours=24)

_MIME_BY_SIGNATURE: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GenerationCreateResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    status_url: str
    idempotent_replay: bool = False


class GenerationErrorResponse(StrictAPIModel):
    code: str
    message: str
    retryable: bool


class GenerationSlideResponse(StrictAPIModel):
    slide_key: str
    position: int
    status: SlideStatus
    progress: int
    provider_used: str | None = None
    result_url: str | None = None
    warning: str | None = None
    error: GenerationErrorResponse | None = None


class MarketplaceTextResponse(StrictAPIModel):
    title: str = Field(min_length=10, max_length=180)
    description: str = Field(min_length=1000, max_length=5000)
    characteristics: tuple[str, ...] = Field(min_length=3, max_length=12)

    @classmethod
    def from_domain(cls, content: MarketplaceTextContent) -> "MarketplaceTextResponse":
        return cls(
            title=content.title,
            description=content.description,
            characteristics=content.characteristics,
        )


class GenerationStatusResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    progress: int
    provider_used: str | None = None
    warning: str | None = None
    archive_url: str | None = None
    marketplace_text: MarketplaceTextResponse | None = None
    slides: tuple[GenerationSlideResponse, ...]
    error: GenerationErrorResponse | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class GenerationHistoryItemResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    progress: int
    product_category: str | None = None
    thumbnail_url: str | None = None
    thumbnail_mime_type: str | None = None
    thumbnail_size_bytes: int | None = Field(default=None, ge=1, le=100 * 1024)
    archive_status: Literal["available", "expired", "pending", "unavailable"]
    archive_url: str | None = None
    archive_expires_at: str | None = None
    provider_used: str | None = None
    warning: str | None = None
    created_at: str
    completed_at: str | None = None


class GenerationForm(StrictAPIModel):
    """Strictly validated non-file fields from multipart input."""

    product_category: str | None = Field(default=None, max_length=128)
    engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD
    post_processing_mode: GenerationPostProcessingMode = GenerationPostProcessingMode.FAST
    apply_text_overlays: bool = False
    overlay_texts: dict[str, str] = Field(default_factory=dict)

    @field_validator("engine_mode", mode="before")
    @classmethod
    def parse_engine_mode(cls, value: object) -> GenerationEngineMode:
        return _parse_engine_mode(value)

    @field_validator("post_processing_mode", mode="before")
    @classmethod
    def parse_post_processing_mode(cls, value: object) -> GenerationPostProcessingMode:
        return _parse_post_processing_mode(value)

    @field_validator("product_category")
    @classmethod
    def clean_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("overlay_texts")
    @classmethod
    def validate_overlay_texts(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"cover", "macro", "lifestyle", "technical", "trust"}
        if set(value) - allowed:
            raise ValueError("overlay_texts contains an unknown slide key.")
        cleaned: dict[str, str] = {}
        for key, text in value.items():
            normalised = text.strip()
            if not normalised or len(normalised) > 300:
                raise ValueError("Each overlay text must contain 1-300 characters.")
            cleaned[key] = normalised
        return cleaned


class ModelModeRequest(StrictAPIModel):
    """JSON contract for clothing virtual try-on on an AI model."""

    source_image_object_key: str = Field(
        min_length=16,
        max_length=1024,
        pattern=r"^[A-Za-z0-9._/\-]+$",
        description="Private S3 object key of the uploaded clothing source image.",
    )
    height_cm: int = Field(ge=140, le=220, description="AI model height in centimeters.")
    body_type: BodyType
    ethnicity: Ethnicity
    engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD
    post_processing_mode: GenerationPostProcessingMode = GenerationPostProcessingMode.FAST
    background: str | None = Field(default=None, min_length=3, max_length=160)
    pose: str | None = Field(default=None, min_length=3, max_length=160)

    @field_validator("engine_mode", mode="before")
    @classmethod
    def parse_engine_mode(cls, value: object) -> GenerationEngineMode:
        return _parse_engine_mode(value)

    @field_validator("post_processing_mode", mode="before")
    @classmethod
    def parse_post_processing_mode(cls, value: object) -> GenerationPostProcessingMode:
        return _parse_post_processing_mode(value)

    @field_validator("source_image_object_key")
    @classmethod
    def validate_source_key(cls, value: str) -> str:
        cleaned = value.strip().replace("\\", "/")
        parts = [part for part in cleaned.split("/") if part]
        if cleaned.startswith("/") or "//" in cleaned or ".." in parts:
            raise ValueError("source_image_object_key must be a safe relative S3 key.")
        if not cleaned.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            raise ValueError("source_image_object_key must point to JPEG, PNG, or WebP.")
        return cleaned

    @field_validator("background", "pose")
    @classmethod
    def clean_optional_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None


async def parse_generation_form(
    product_category: Annotated[str | None, Form(max_length=128)] = None,
    engine_mode: Annotated[GenerationEngineMode, Form()] = GenerationEngineMode.STANDARD,
    post_processing_mode: Annotated[
        GenerationPostProcessingMode,
        Form(),
    ] = GenerationPostProcessingMode.FAST,
    apply_text_overlays: Annotated[bool, Form()] = False,
    overlay_texts: Annotated[str | None, Form(max_length=3000)] = None,
) -> GenerationForm:
    parsed_overlays: dict[str, str] = {}
    if overlay_texts:
        try:
            raw = json.loads(overlay_texts)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="overlay_texts must be a JSON object.",
            ) from exc
        if not isinstance(raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="overlay_texts must map slide names to strings.",
            )
        parsed_overlays = raw
    try:
        return GenerationForm(
            product_category=product_category,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            apply_text_overlays=apply_text_overlays,
            overlay_texts=parsed_overlays,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/model",
    response_model=GenerationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create AI Model virtual try-on generation",
    description=(
        "Accepts JSON typage parameters and queues a realistic virtual try-on task "
        "that transfers clothing from a private source image onto an AI model."
    ),
)
async def create_model_generation(
    payload: ModelModeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> GenerationCreateResponse:
    """Queue the JSON-only Model mode without blocking on external VTO APIs."""

    _validate_owned_source_object_key(payload.source_image_object_key, current_user.id)
    engine_mode = _effective_engine_mode(payload.engine_mode, payload.post_processing_mode)
    _ensure_generation_options_allowed(engine_mode, payload.post_processing_mode, current_user)
    repository = GenerationRepository(db_session)
    if idempotency_key:
        idempotency_key = idempotency_key.strip()
        existing = await repository.find_idempotent_job(
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return GenerationCreateResponse(
                task_id=existing.id,
                status=GenerationJobStatus(existing.status),
                status_url=f"/api/v1/generations/{existing.id}",
                idempotent_replay=True,
            )

    settings = get_settings()
    generation_cost = _generation_cost_for_mode(payload.post_processing_mode)
    if settings.generation_charge_coins and current_user.ai_coins < generation_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient AI-coin balance.",
        )

    task = build_model_vto_task(
        typage=ModelTypage(
            height_cm=payload.height_cm,
            body_type=payload.body_type,
            ethnicity=payload.ethnicity,
        ),
        background=payload.background,
        pose=payload.pose,
    )
    try:
        job, created = await repository.create_job(
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            subscription_status=current_user.subscription_status.value,
            engine_mode=engine_mode,
            post_processing_mode=payload.post_processing_mode,
            input_object_key=payload.source_image_object_key,
            product_category=MODEL_VTO_PRODUCT_CATEGORY,
            apply_text_overlays=False,
            overlay_texts={},
            slide_tasks=(task,),
        )
        if created:
            await invalidate_generation_history_cache(current_user.id)
        return GenerationCreateResponse(
            task_id=job.id,
            status=GenerationJobStatus(job.status),
            status_url=f"/api/v1/generations/{job.id}",
            idempotent_replay=not created,
        )
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Could not create durable model generation job")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create model generation task.",
        ) from exc


@router.post(
    "",
    response_model=GenerationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation(
    file: Annotated[UploadFile, File(description="JPEG, PNG, or WebP product photo")],
    form: Annotated[GenerationForm, Depends(parse_generation_form)],
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> GenerationCreateResponse:
    """Persist a durable generation command and return before AI work begins."""

    engine_mode = _effective_engine_mode(form.engine_mode, form.post_processing_mode)
    _ensure_generation_options_allowed(engine_mode, form.post_processing_mode, current_user)
    repository = GenerationRepository(db_session)
    if idempotency_key:
        idempotency_key = idempotency_key.strip()
        existing = await repository.find_idempotent_job(
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            await file.close()
            return GenerationCreateResponse(
                task_id=existing.id,
                status=GenerationJobStatus(existing.status),
                status_url=f"/api/v1/generations/{existing.id}",
                idempotent_replay=True,
            )

    settings = get_settings()
    generation_cost = _generation_cost_for_mode(form.post_processing_mode)
    if settings.generation_charge_coins and current_user.ai_coins < generation_cost:
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient AI-coin balance.",
        )
    storage = None
    input_key: str | None = None
    uploaded = False
    try:
        image_bytes = await _read_bounded_upload(
            file,
            max_bytes=settings.generation_max_upload_bytes,
        )
        mime_type, extension = await _validate_image(image_bytes, file.content_type)
        input_key = f"generation-inputs/{current_user.id}/{uuid4().hex}{extension}"
        storage = get_s3_storage()
        await storage.upload_bytes(
            object_key=input_key,
            data=image_bytes,
            content_type=mime_type,
            presign=False,
        )
        uploaded = True
        job, created = await repository.create_job(
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            subscription_status=current_user.subscription_status.value,
            engine_mode=engine_mode,
            post_processing_mode=form.post_processing_mode,
            input_object_key=input_key,
            product_category=form.product_category,
            apply_text_overlays=form.apply_text_overlays,
            overlay_texts=form.overlay_texts,
            slide_tasks=await build_series_tasks_cached(form.product_category),
        )
        if not created:
            await _best_effort_delete(storage, input_key)
        if created:
            await invalidate_generation_history_cache(current_user.id)
        return GenerationCreateResponse(
            task_id=job.id,
            status=GenerationJobStatus(job.status),
            status_url=f"/api/v1/generations/{job.id}",
            idempotent_replay=not created,
        )
    except BillingValidationError as exc:
        if uploaded and storage is not None and input_key is not None:
            await _best_effort_delete(storage, input_key)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except S3StorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        ) from exc
    except S3StorageError as exc:
        logger.exception("Generation input upload failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is temporarily unavailable.",
        ) from exc
    except HTTPException:
        if uploaded and storage is not None and input_key is not None:
            await _best_effort_delete(storage, input_key)
        raise
    except Exception as exc:
        if uploaded and storage is not None and input_key is not None:
            await _best_effort_delete(storage, input_key)
        logger.exception("Could not create durable generation job")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create generation task.",
        ) from exc
    finally:
        await file.close()


@router.get("/history", response_model=list[GenerationHistoryItemResponse])
async def list_generation_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GenerationHistoryItemResponse]:
    """Return personal cabinet generation history with durable thumbnails."""

    cached_items = await get_cached_generation_history(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
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
            logger.debug("Generation history cache payload invalid", exc_info=True)

    repository = GenerationRepository(db_session)
    jobs = await repository.list_generation_history_for_user(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    storage = None
    try:
        storage = get_s3_storage()
    except S3StorageError:
        logger.warning("S3 unavailable while building generation history", exc_info=True)

    now = datetime.now(UTC)
    response: list[GenerationHistoryItemResponse] = []
    for job in jobs:
        thumbnail_url: str | None = None
        if storage is not None and job.thumbnail_object_key:
            try:
                thumbnail_url = await storage.generate_presigned_url(
                    object_key=job.thumbnail_object_key
                )
            except S3StorageError:
                logger.warning(
                    "Could not presign thumbnail for job %s",
                    job.id,
                    exc_info=True,
                )

        archive_url: str | None = None
        archive_status, archive_expires_at = _archive_access_state(job, now)
        if archive_status == "available" and storage is not None and job.archive_object_key:
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
                thumbnail_url=thumbnail_url,
                thumbnail_mime_type=job.thumbnail_mime_type,
                thumbnail_size_bytes=job.thumbnail_size_bytes,
                archive_status=archive_status,
                archive_url=archive_url,
                archive_expires_at=archive_expires_at.isoformat()
                if archive_expires_at
                else None,
                provider_used=job.provider_used,
                warning=job.warning,
                created_at=job.created_at.isoformat(),
                completed_at=job.completed_at.isoformat() if job.completed_at else None,
            )
        )
    await set_cached_generation_history(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        items=[item.model_dump(mode="json") for item in response],
    )
    return response


@router.get("/{task_id}", response_model=GenerationStatusResponse)
async def get_generation_status(
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationStatusResponse:
    """Return canonical DB status, using Redis only as a short-lived hot cache."""

    cache_key = f"generation:status:{current_user.id}:{task_id}"
    try:
        cached = await get_cached_json(cache_key)
        if cached is not None:
            return GenerationStatusResponse.model_validate_json(
                json.dumps(cached, ensure_ascii=False)
            )
    except (RedisUnavailableError, ValueError):
        logger.debug("Generation status cache miss/failure", exc_info=True)

    repository = GenerationRepository(db_session)
    job = await repository.get_job_for_user(task_id, current_user.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation task was not found.",
        )

    storage = None
    try:
        storage = get_s3_storage()
    except S3StorageError:
        logger.warning("S3 unavailable while building generation status", exc_info=True)

    archive_url: str | None = None
    archive_status, _archive_expires_at = _archive_access_state(job, datetime.now(UTC))
    if storage is not None and job.archive_object_key and archive_status == "available":
        try:
            archive_url = await storage.generate_presigned_url(
                object_key=job.archive_object_key
            )
        except S3StorageError:
            logger.warning(
                "Could not presign archive for job %s", job.id, exc_info=True
            )

    async def _slide_response(slide: Any) -> GenerationSlideResponse:
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
        return GenerationSlideResponse(
            slide_key=slide.slide_key,
            position=slide.position,
            status=SlideStatus(slide.status),
            progress=slide.progress,
            provider_used=slide.provider_used,
            result_url=result_url,
            warning=slide.warning,
            error=slide_error,
        )

    slides = tuple(
        await asyncio.gather(*(_slide_response(slide) for slide in job.slides))
    )
    job_error = None
    if job.error_code and job.error_message:
        job_error = GenerationErrorResponse(
            code=job.error_code,
            message=job.error_message,
            retryable=job.error_retryable,
        )
    marketplace_text = _marketplace_text_response(getattr(job, "marketplace_text", None))
    response = GenerationStatusResponse(
        task_id=job.id,
        status=GenerationJobStatus(job.status),
        progress=job.progress,
        provider_used=job.provider_used,
        warning=job.warning,
        archive_url=archive_url,
        marketplace_text=marketplace_text,
        slides=slides,
        error=job_error,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
    try:
        await cache_json(
            cache_key,
            response.model_dump(mode="json"),
            ttl_seconds=(
                get_settings().generation_status_terminal_cache_ttl_seconds
                if response.status
                in (GenerationJobStatus.COMPLETED, GenerationJobStatus.FAILED)
                else get_settings().generation_status_cache_ttl_seconds
            ),
        )
    except RedisUnavailableError:
        pass
    return response


def _validate_owned_source_object_key(object_key: str, user_id: UUID) -> None:
    allowed_prefixes = (
        f"generation-inputs/{user_id}/",
        f"model-inputs/{user_id}/",
        f"user-uploads/{user_id}/",
    )
    if not object_key.startswith(allowed_prefixes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Source image object key does not belong to the current user.",
        )


def _ensure_engine_mode_allowed(engine_mode: GenerationEngineMode, user: User) -> None:
    if engine_mode == GenerationEngineMode.PREMIUM and not user.subscription_status.is_paid():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium generation mode requires an active paid subscription.",
        )


def _ensure_generation_options_allowed(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
    user: User,
) -> None:
    _ensure_engine_mode_allowed(engine_mode, user)
    if (
        post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX
        and not user.subscription_status.is_paid()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HD Face Fix post-processing requires an active paid subscription.",
        )


def _effective_engine_mode(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
) -> GenerationEngineMode:
    if post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX:
        return GenerationEngineMode.PREMIUM
    return engine_mode


def _generation_cost_for_mode(post_processing_mode: GenerationPostProcessingMode) -> int:
    settings = get_settings()
    if post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX:
        return settings.generation_hd_face_fix_cost_coins
    return settings.generation_fast_cost_coins


def _parse_engine_mode(value: object) -> GenerationEngineMode:
    if isinstance(value, GenerationEngineMode):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        try:
            return GenerationEngineMode(cleaned)
        except ValueError as exc:
            raise ValueError("engine_mode must be 'standard' or 'premium'.") from exc
    raise ValueError("engine_mode must be 'standard' or 'premium'.")


def _parse_post_processing_mode(value: object) -> GenerationPostProcessingMode:
    if isinstance(value, GenerationPostProcessingMode):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        aliases = {
            "quick": GenerationPostProcessingMode.FAST,
            "fast_generation": GenerationPostProcessingMode.FAST,
            "hd": GenerationPostProcessingMode.HD_FACE_FIX,
            "hd_quality": GenerationPostProcessingMode.HD_FACE_FIX,
            "hd_quality_face_fix": GenerationPostProcessingMode.HD_FACE_FIX,
        }
        if cleaned in aliases:
            return aliases[cleaned]
        try:
            return GenerationPostProcessingMode(cleaned)
        except ValueError as exc:
            raise ValueError(
                "post_processing_mode must be 'fast' or 'hd_face_fix'."
            ) from exc
    raise ValueError("post_processing_mode must be 'fast' or 'hd_face_fix'.")


def _marketplace_text_response(value: object) -> MarketplaceTextResponse | None:
    if not value:
        return None
    if isinstance(value, MarketplaceTextContent):
        return MarketplaceTextResponse.from_domain(value)
    if isinstance(value, dict):
        return MarketplaceTextResponse.from_domain(MarketplaceTextContent.model_validate(value))
    return None


async def _read_bounded_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Image exceeds the {max_bytes}-byte upload limit.",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty.",
        )
    return b"".join(chunks)


async def _best_effort_delete(storage: Any, object_key: str) -> None:
    try:
        await storage.delete_object(object_key=object_key)
    except S3StorageError:
        logger.warning("Could not clean up orphan input %s", object_key, exc_info=True)


def _archive_access_state(
    job: Any,
    now: datetime,
) -> tuple[Literal["available", "expired", "pending", "unavailable"], datetime | None]:
    if not job.archive_object_key:
        if job.status == GenerationJobStatus.FAILED.value:
            return "unavailable", None
        if job.status == GenerationJobStatus.COMPLETED.value:
            return "unavailable", None
        return "pending", None
    if job.completed_at is None:
        return "pending", None

    expires_at = _to_utc(job.completed_at) + _ARCHIVE_RETENTION
    if _to_utc(now) < expires_at:
        return "available", expires_at
    return "expired", expires_at


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _validate_image(
    data: bytes,
    claimed_content_type: str | None,
) -> tuple[str, str]:
    mime_type: str | None = None
    extension: str | None = None
    for signature, candidate_mime, candidate_extension in _MIME_BY_SIGNATURE:
        if data.startswith(signature):
            mime_type, extension = candidate_mime, candidate_extension
            break
    if (
        mime_type is None
        and len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        mime_type, extension = "image/webp", ".webp"
    if mime_type is None or extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image signature. Allowed: JPEG, PNG, WebP.",
        )
    if claimed_content_type and claimed_content_type != mime_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Declared content type does not match image bytes.",
        )

    def _verify() -> None:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()

    try:
        await asyncio.to_thread(_verify)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image is malformed or cannot be decoded.",
        ) from exc
    return mime_type, extension
