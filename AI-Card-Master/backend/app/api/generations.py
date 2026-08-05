"""Fast generation API backed by PostgreSQL, Celery, Redis, and S3."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.core.config import get_settings
from app.domain.generation import GenerationJobStatus, SlideStatus
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
    get_s3_storage,
)
from app.services.series_generator import build_series_tasks_cached

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/generations", tags=["generations"])

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


class GenerationStatusResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    progress: int
    provider_used: str | None = None
    warning: str | None = None
    archive_url: str | None = None
    slides: tuple[GenerationSlideResponse, ...]
    error: GenerationErrorResponse | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class GenerationForm(StrictAPIModel):
    """Strictly validated non-file fields from multipart input."""

    product_category: str | None = Field(default=None, max_length=128)
    apply_text_overlays: bool = False
    overlay_texts: dict[str, str] = Field(default_factory=dict)

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


async def parse_generation_form(
    product_category: Annotated[str | None, Form(max_length=128)] = None,
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
            apply_text_overlays=apply_text_overlays,
            overlay_texts=parsed_overlays,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
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
    if settings.generation_charge_coins and current_user.ai_coins < 1:
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
            input_object_key=input_key,
            product_category=form.product_category,
            apply_text_overlays=form.apply_text_overlays,
            overlay_texts=form.overlay_texts,
            slide_tasks=await build_series_tasks_cached(form.product_category),
        )
        if not created:
            await _best_effort_delete(storage, input_key)
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
    if storage is not None and job.archive_object_key:
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
    response = GenerationStatusResponse(
        task_id=job.id,
        status=GenerationJobStatus(job.status),
        progress=job.progress,
        provider_used=job.provider_used,
        warning=job.warning,
        archive_url=archive_url,
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
            ttl_seconds=5,
        )
    except RedisUnavailableError:
        pass
    return response


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
