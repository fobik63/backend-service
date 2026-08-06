"""Smart Variant Sync API: one photo → N fabric color variants."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.smart_variant_service import (
    SmartVariantNotFoundError,
    SmartVariantService,
    SmartVariantValidationError,
)
from app.core.config import get_settings
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.domain.smart_variant import (
    VariantItemStatus,
    VariantSyncStatus,
    parse_notify_channels,
)
from app.infrastructure.smart_variant_factory import build_smart_variant_service
from app.infrastructure.celery_app import celery_app
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/smart-variants", tags=["smart-variants"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VariantItemResponse(StrictAPIModel):
    id: UUID
    position: int
    color_name: str
    color_hex: str | None = None
    color_slug: str
    status: VariantItemStatus
    generation_job_id: UUID | None = None
    status_url: str | None = None
    error_message: str | None = None


class VariantSyncResponse(StrictAPIModel):
    sync_id: UUID
    status: VariantSyncStatus
    product_category: str | None
    progress: int = Field(ge=0, le=100)
    total_items: int
    completed_items: int
    failed_items: int
    skipped_items: int
    notify_telegram: bool
    notify_push: bool
    telegram_notified: bool
    push_notified: bool
    status_url: str
    error_message: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    items: tuple[VariantItemResponse, ...] = ()
    idempotent_replay: bool = False


class VariantSyncCreateResponse(StrictAPIModel):
    sync_id: UUID
    status: VariantSyncStatus
    status_url: str
    total_colors: int = Field(ge=1)
    idempotent_replay: bool = False


def _parse_engine_mode(value: object) -> GenerationEngineMode:
    if isinstance(value, GenerationEngineMode):
        return value
    if isinstance(value, str):
        try:
            return GenerationEngineMode(value.strip().lower())
        except ValueError as exc:
            raise ValueError("engine_mode must be 'standard' or 'premium'.") from exc
    raise ValueError("engine_mode must be 'standard' or 'premium'.")


def _parse_post_processing_mode(value: object) -> GenerationPostProcessingMode:
    if isinstance(value, GenerationPostProcessingMode):
        return value
    if isinstance(value, str):
        try:
            return GenerationPostProcessingMode(value.strip().lower())
        except ValueError as exc:
            raise ValueError(
                "post_processing_mode must be 'fast' or 'hd_face_fix'."
            ) from exc
    raise ValueError("post_processing_mode must be 'fast' or 'hd_face_fix'.")


def _generation_cost_for_mode(post_processing_mode: GenerationPostProcessingMode) -> int:
    settings = get_settings()
    if post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX:
        return settings.generation_hd_face_fix_cost_coins
    return settings.generation_fast_cost_coins


def _ensure_options_allowed(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
    user: User,
) -> None:
    if engine_mode == GenerationEngineMode.PREMIUM and not user.subscription_status.is_paid():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium generation mode requires an active paid subscription.",
        )
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


def _sync_progress(sync) -> int:
    if sync.total_items <= 0:
        return 0
    finished = sync.completed_items + sync.failed_items + sync.skipped_items
    return min(100, int(finished * 100 / sync.total_items))


def _item_response(item) -> VariantItemResponse:
    status_url = (
        f"/api/v1/generations/{item.generation_job_id}"
        if item.generation_job_id is not None
        else None
    )
    return VariantItemResponse(
        id=item.id,
        position=item.position,
        color_name=item.color_name,
        color_hex=item.color_hex,
        color_slug=item.color_slug,
        status=item.status,
        generation_job_id=item.generation_job_id,
        status_url=status_url,
        error_message=item.error_message,
    )


def _sync_response(sync, *, idempotent_replay: bool = False) -> VariantSyncResponse:
    return VariantSyncResponse(
        sync_id=sync.id,
        status=sync.status,
        product_category=sync.product_category,
        progress=_sync_progress(sync),
        total_items=sync.total_items,
        completed_items=sync.completed_items,
        failed_items=sync.failed_items,
        skipped_items=sync.skipped_items,
        notify_telegram=sync.notify_telegram,
        notify_push=sync.notify_push,
        telegram_notified=sync.telegram_notified_at is not None,
        push_notified=sync.push_notified_at is not None,
        status_url=f"/api/v1/smart-variants/{sync.id}",
        error_message=sync.error_message,
        created_at=sync.created_at.isoformat(),
        updated_at=sync.updated_at.isoformat(),
        completed_at=sync.completed_at.isoformat() if sync.completed_at else None,
        items=tuple(_item_response(item) for item in sync.items),
        idempotent_replay=idempotent_replay,
    )


def get_smart_variant_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> SmartVariantService:
    return build_smart_variant_service(db_session)


async def _read_bounded_image(file: UploadFile, *, max_bytes: int) -> bytes:
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


@router.post(
    "",
    response_model=VariantSyncCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start Smart Variant Sync from one product photo",
    description=(
        "Upload one product photo and a list of target fabric colors. "
        "The AI recolors the garment for each color (preserving texture and shadows), "
        "adapts infographic overlays, and enqueues a full card generation per variant."
    ),
)
async def create_smart_variant_sync(
    file: Annotated[UploadFile, File(description="Source product photo (JPEG/PNG/WebP)")],
    colors: Annotated[
        str,
        Form(
            description=(
                "Target colors: JSON array "
                '[{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#C41E3A"}] '
                "or comma-separated names/hex (Black,#C41E3A,navy)."
            ),
        ),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    product_category: Annotated[str | None, Form(max_length=128)] = None,
    engine_mode: Annotated[str, Form()] = "standard",
    post_processing_mode: Annotated[str, Form()] = "fast",
    apply_text_overlays: Annotated[bool, Form()] = True,
    notify_channels: Annotated[
        str | None,
        Form(description="Comma-separated: telegram,push"),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> VariantSyncCreateResponse:
    try:
        parsed_engine = _parse_engine_mode(engine_mode)
        parsed_post = _parse_post_processing_mode(post_processing_mode)
        channels = parse_notify_channels(notify_channels)
    except ValueError as exc:
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    effective_engine = _effective_engine_mode(parsed_engine, parsed_post)
    _ensure_options_allowed(effective_engine, parsed_post, current_user)

    settings = get_settings()
    service = build_smart_variant_service(
        db_session,
        coins_per_color=_generation_cost_for_mode(parsed_post),
    )

    cleaned_category = product_category.strip() if product_category else None
    if cleaned_category == "":
        cleaned_category = None

    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    try:
        image_bytes = await _read_bounded_image(
            file,
            max_bytes=settings.generation_max_upload_bytes,
        )
        sync, created = await service.create_sync(
            user_id=current_user.id,
            subscription_status=current_user.subscription_status.value,
            image_bytes=image_bytes,
            colors_raw=colors,
            product_category=cleaned_category,
            engine_mode=effective_engine,
            post_processing_mode=parsed_post,
            apply_text_overlays=apply_text_overlays,
            notify_channels=channels,
            idempotency_key=idempotency_key,
            ai_coins=current_user.ai_coins,
        )
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except SmartVariantValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except S3StorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        ) from exc
    except S3StorageError as exc:
        logger.exception("Smart variant source upload failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is temporarily unavailable.",
        ) from exc
    finally:
        await file.close()

    if created:
        celery_app.send_task(
            "smart_variant.recolor_and_enqueue",
            args=[str(sync.id), current_user.subscription_status.value],
        )

    return VariantSyncCreateResponse(
        sync_id=sync.id,
        status=sync.status,
        status_url=f"/api/v1/smart-variants/{sync.id}",
        total_colors=max(1, sync.total_items),
        idempotent_replay=not created,
    )


@router.get(
    "/{sync_id}",
    response_model=VariantSyncResponse,
    summary="Get Smart Variant Sync status",
)
async def get_smart_variant_sync(
    sync_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SmartVariantService, Depends(get_smart_variant_service)],
) -> VariantSyncResponse:
    try:
        sync = await service.get_sync_for_user(
            user_id=current_user.id,
            sync_id=sync_id,
        )
    except SmartVariantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _sync_response(sync)
