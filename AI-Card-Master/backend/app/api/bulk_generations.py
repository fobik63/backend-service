"""Bulk Generation API: ZIP upload, batch status, in-app push inbox."""

from __future__ import annotations

import json
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
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.captcha import enforce_generation_behavioral_limit
from app.api.dependencies.auth import get_current_user
from app.application.bulk_generation_service import (
    BulkGenerationNotFoundError,
    BulkGenerationService,
    BulkGenerationValidationError,
)
from app.core.config import get_settings
from app.core.pricing import generation_cost_for_mode
from app.domain.bulk_generation import (
    BulkBatchStatus,
    BulkItemStatus,
    parse_notify_channels,
)
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.infrastructure.bulk_generation_factory import build_bulk_generation_service
from app.infrastructure.celery_app import celery_app
from app.models.bulk_generation import UserPushNotification
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/bulk-generations", tags=["bulk-generations"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BulkItemResponse(StrictAPIModel):
    id: UUID
    position: int
    product_key: str
    source_path: str
    status: BulkItemStatus
    generation_job_id: UUID | None = None
    status_url: str | None = None
    error_message: str | None = None


class BulkBatchResponse(StrictAPIModel):
    batch_id: UUID
    status: BulkBatchStatus
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
    items: tuple[BulkItemResponse, ...] = ()
    idempotent_replay: bool = False


class BulkBatchCreateResponse(StrictAPIModel):
    batch_id: UUID
    status: BulkBatchStatus
    status_url: str
    total_items_hint: int = Field(
        ge=0,
        description="Product images detected in the ZIP before background unpack.",
    )
    idempotent_replay: bool = False


class PushNotificationResponse(StrictAPIModel):
    id: UUID
    title: str
    body: str
    data: dict[str, str]
    read_at: str | None
    created_at: str


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
    """Delegate to the shared pricing matrix (FAST=1 / HD Face Fix=3 defaults)."""

    return generation_cost_for_mode(post_processing_mode)


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


def _batch_progress(batch) -> int:
    if batch.total_items <= 0:
        return 0
    finished = batch.completed_items + batch.failed_items + batch.skipped_items
    return min(100, int(finished * 100 / batch.total_items))


def _item_response(item) -> BulkItemResponse:
    status_url = (
        f"/api/v1/generations/{item.generation_job_id}"
        if item.generation_job_id is not None
        else None
    )
    return BulkItemResponse(
        id=item.id,
        position=item.position,
        product_key=item.product_key,
        source_path=item.source_path,
        status=item.status,
        generation_job_id=item.generation_job_id,
        status_url=status_url,
        error_message=item.error_message,
    )


def _batch_response(batch, *, idempotent_replay: bool = False) -> BulkBatchResponse:
    return BulkBatchResponse(
        batch_id=batch.id,
        status=batch.status,
        product_category=batch.product_category,
        progress=_batch_progress(batch),
        total_items=batch.total_items,
        completed_items=batch.completed_items,
        failed_items=batch.failed_items,
        skipped_items=batch.skipped_items,
        notify_telegram=batch.notify_telegram,
        notify_push=batch.notify_push,
        telegram_notified=batch.telegram_notified_at is not None,
        push_notified=batch.push_notified_at is not None,
        status_url=f"/api/v1/bulk-generations/{batch.id}",
        error_message=batch.error_message,
        created_at=batch.created_at.isoformat(),
        updated_at=batch.updated_at.isoformat(),
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        items=tuple(_item_response(item) for item in batch.items),
        idempotent_replay=idempotent_replay,
    )


def get_bulk_generation_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> BulkGenerationService:
    return build_bulk_generation_service(db_session)


async def _read_bounded_zip(file: UploadFile, *, max_bytes: int) -> bytes:
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
                detail=f"ZIP exceeds the {max_bytes}-byte upload limit.",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded ZIP is empty.",
        )
    return b"".join(chunks)


@router.post(
    "",
    response_model=BulkBatchCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start bulk generation from a ZIP of product photos",
    description=(
        "Upload one ZIP with up to 20 product images (flat files or one folder "
        "per SKU). The batch is unpacked and processed in the background using "
        "the selected style preset (product_category). When the whole batch "
        "finishes, the user is notified via Telegram and/or in-app push."
    ),
)
async def create_bulk_generation(
    file: Annotated[UploadFile, File(description="ZIP with 1–20 product images")],
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_generation_behavioral_limit)],
    product_category: Annotated[str | None, Form(max_length=128)] = None,
    engine_mode: Annotated[str, Form()] = "standard",
    post_processing_mode: Annotated[str, Form()] = "fast",
    apply_text_overlays: Annotated[bool, Form()] = False,
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
) -> BulkBatchCreateResponse:
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
    service = build_bulk_generation_service(
        db_session,
        coins_per_product=_generation_cost_for_mode(parsed_post),
    )

    cleaned_category = product_category.strip() if product_category else None
    if cleaned_category == "":
        cleaned_category = None

    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    try:
        zip_bytes = await _read_bounded_zip(
            file,
            max_bytes=settings.bulk_generation_max_zip_bytes,
        )
        batch, created, product_count = await service.create_batch_from_zip(
            user_id=current_user.id,
            subscription_status=current_user.subscription_status.value,
            zip_bytes=zip_bytes,
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
    except BulkGenerationValidationError as exc:
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
        logger.exception("Bulk ZIP upload failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is temporarily unavailable.",
        ) from exc
    finally:
        await file.close()

    if created:
        celery_app.send_task(
            "bulk.unpack_and_enqueue",
            args=[str(batch.id), current_user.subscription_status.value],
        )

    return BulkBatchCreateResponse(
        batch_id=batch.id,
        status=batch.status,
        status_url=f"/api/v1/bulk-generations/{batch.id}",
        total_items_hint=product_count,
        idempotent_replay=not created,
    )


@router.get(
    "/notifications",
    response_model=tuple[PushNotificationResponse, ...],
    summary="List recent in-app push notifications",
)
async def list_push_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[PushNotificationResponse, ...]:
    rows = (
        await db_session.scalars(
            select(UserPushNotification)
            .where(UserPushNotification.user_id == current_user.id)
            .order_by(UserPushNotification.created_at.desc())
            .limit(limit)
        )
    ).all()
    result: list[PushNotificationResponse] = []
    for row in rows:
        try:
            data = json.loads(row.data_json)
            if not isinstance(data, dict):
                data = {}
            cleaned = {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            cleaned = {}
        result.append(
            PushNotificationResponse(
                id=row.id,
                title=row.title,
                body=row.body,
                data=cleaned,
                read_at=row.read_at.isoformat() if row.read_at else None,
                created_at=row.created_at.isoformat(),
            )
        )
    return tuple(result)


@router.get(
    "/{batch_id}",
    response_model=BulkBatchResponse,
    summary="Get bulk generation batch status",
)
async def get_bulk_generation(
    batch_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BulkGenerationService, Depends(get_bulk_generation_service)],
) -> BulkBatchResponse:
    try:
        batch = await service.get_batch_for_user(
            user_id=current_user.id,
            batch_id=batch_id,
        )
    except BulkGenerationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _batch_response(batch)
