"""Custom Brand LoRA API: upload brandbook refs → personal style filter."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.brand_lora_service import (
    BrandLoraForbiddenError,
    BrandLoraNotFoundError,
    BrandLoraService,
    BrandLoraValidationError,
)
from app.domain.brand_lora import BrandLoraStatus
from app.infrastructure.brand_lora_factory import build_brand_lora_service
from app.infrastructure.celery_app import celery_app
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/brand-loras", tags=["brand-loras"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrandLoraReferenceResponse(StrictAPIModel):
    id: UUID
    position: int
    object_key: str
    mime_type: str
    size_bytes: int


class BrandLoraResponse(StrictAPIModel):
    profile_id: UUID
    name: str
    trigger_word: str
    status: BrandLoraStatus
    is_active: bool
    brand_style_prompt: str | None = None
    lora_weights_url: str | None = None
    lora_scale: float
    reference_count: int
    training_progress: int = Field(ge=0, le=100)
    coins_charged: int
    notes: str | None = None
    error_message: str | None = None
    status_url: str
    created_at: str
    updated_at: str
    trained_at: str | None = None
    references: tuple[BrandLoraReferenceResponse, ...] = ()


class BrandLoraListResponse(StrictAPIModel):
    items: tuple[BrandLoraResponse, ...]
    training_cost_coins: int
    min_references: int
    max_references: int


class BrandLoraCreateResponse(StrictAPIModel):
    profile_id: UUID
    status: BrandLoraStatus
    status_url: str
    trigger_word: str
    reference_count: int
    coins_charged: int


def get_brand_lora_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> BrandLoraService:
    return build_brand_lora_service(db_session)


def _profile_response(profile, *, include_references: bool = False) -> BrandLoraResponse:
    refs: tuple[BrandLoraReferenceResponse, ...] = ()
    if include_references:
        refs = tuple(
            BrandLoraReferenceResponse(
                id=item.id,
                position=item.position,
                object_key=item.object_key,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
            )
            for item in profile.references
        )
    return BrandLoraResponse(
        profile_id=profile.id,
        name=profile.name,
        trigger_word=profile.trigger_word,
        status=profile.status,
        is_active=profile.is_active,
        brand_style_prompt=profile.brand_style_prompt,
        lora_weights_url=profile.lora_weights_url,
        lora_scale=profile.lora_scale,
        reference_count=profile.reference_count,
        training_progress=profile.training_progress,
        coins_charged=profile.coins_charged,
        notes=profile.notes,
        error_message=profile.error_message,
        status_url=f"/api/v1/brand-loras/{profile.id}",
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
        trained_at=profile.trained_at.isoformat() if profile.trained_at else None,
        references=refs,
    )


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
    response_model=BrandLoraCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_brand_lora(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
    brand_name: Annotated[str, Form(min_length=2, max_length=64)],
    files: Annotated[
        list[UploadFile],
        File(description="20–30 JPEG/PNG/WebP brand reference photos"),
    ],
    notes: Annotated[str | None, Form(max_length=500)] = None,
) -> BrandLoraCreateResponse:
    """Upload brandbook references and queue Custom LoRA / BrandDNA training."""

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one reference photo is required.",
        )
    images: list[bytes] = []
    try:
        for upload in files:
            images.append(
                await _read_bounded_image(
                    upload, max_bytes=service.max_image_bytes
                )
            )
        profile = await service.create_training(
            user_id=current_user.id,
            subscription_status=current_user.subscription_status.value,
            brand_name=brand_name,
            notes=notes,
            images=tuple(images),
            ai_coins=current_user.ai_coins,
        )
    except BrandLoraForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except BrandLoraValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
        ) from exc
    except (S3StorageConfigurationError, S3StorageError) as exc:
        logger.exception("Brand LoRA upload failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable for Brand LoRA uploads.",
        ) from exc
    finally:
        for upload in files:
            await upload.close()

    celery_app.send_task(
        "brand_lora.start_training",
        args=[str(profile.id)],
        queue="brand_lora",
    )
    return BrandLoraCreateResponse(
        profile_id=profile.id,
        status=profile.status,
        status_url=f"/api/v1/brand-loras/{profile.id}",
        trigger_word=profile.trigger_word,
        reference_count=profile.reference_count,
        coins_charged=profile.coins_charged,
    )


@router.get("", response_model=BrandLoraListResponse)
async def list_brand_loras(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
) -> BrandLoraListResponse:
    """List the caller's Brand LoRA profiles (excluding archived)."""

    items = await service.list_for_user(user_id=current_user.id)
    return BrandLoraListResponse(
        items=tuple(_profile_response(item) for item in items),
        training_cost_coins=service.training_cost_coins,
        min_references=service.min_references,
        max_references=service.max_references,
    )


@router.get("/{profile_id}", response_model=BrandLoraResponse)
async def get_brand_lora(
    profile_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
) -> BrandLoraResponse:
    """Poll training status for one Brand LoRA profile."""

    try:
        profile = await service.get_for_user(
            user_id=current_user.id, profile_id=profile_id
        )
    except BrandLoraNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _profile_response(profile, include_references=True)


@router.post("/{profile_id}/activate", response_model=BrandLoraResponse)
async def activate_brand_lora(
    profile_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
) -> BrandLoraResponse:
    """Make a ready Brand LoRA the default filter for all generations."""

    try:
        profile = await service.set_active(
            user_id=current_user.id, profile_id=profile_id, active=True
        )
    except BrandLoraNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except BrandLoraValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _profile_response(profile)


@router.post("/{profile_id}/deactivate", response_model=BrandLoraResponse)
async def deactivate_brand_lora(
    profile_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
) -> BrandLoraResponse:
    """Stop auto-applying the Brand LoRA without archiving it."""

    try:
        profile = await service.set_active(
            user_id=current_user.id, profile_id=profile_id, active=False
        )
    except BrandLoraNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except BrandLoraValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _profile_response(profile)


@router.delete("/{profile_id}", response_model=BrandLoraResponse)
async def archive_brand_lora(
    profile_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BrandLoraService, Depends(get_brand_lora_service)],
) -> BrandLoraResponse:
    """Archive a Brand LoRA profile (soft delete)."""

    try:
        profile = await service.archive(
            user_id=current_user.id, profile_id=profile_id
        )
    except BrandLoraNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _profile_response(profile)
