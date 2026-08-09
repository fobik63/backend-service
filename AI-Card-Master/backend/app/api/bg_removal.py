"""REST API for automatic product background removal."""

from __future__ import annotations

import logging
from typing import Annotated

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

from app.api.dependencies.auth import get_current_user
from app.core.config import get_settings
from app.models.database import get_db_session
from app.models.user import User
from app.services.bg_removal import (
    BG_REMOVAL_COST_COINS,
    BackgroundRemovalEngineError,
    BackgroundRemovalService,
    BackgroundRemovalServiceError,
    BackgroundRemovalUpstreamError,
    BackgroundRemovalValidationError,
)
from app.services.billing_service import BillingNotFoundError, BillingValidationError
from app.services.s3_storage import S3StorageConfigurationError, S3StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "application/octet-stream",
    }
)


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RemoveBgResponse(StrictAPIModel):
    success: bool = True
    cdn_url: str = Field(..., min_length=1)
    object_key: str = Field(..., min_length=1)
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    content_type: str = "image/png"
    cost_coins: int = Field(default=BG_REMOVAL_COST_COINS, ge=0)


def _get_bg_removal_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> BackgroundRemovalService:
    return BackgroundRemovalService(db_session)


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
    "/remove-bg",
    response_model=RemoveBgResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove product background (rembg)",
    description=(
        "Accepts a multipart image upload **or** ``image_url``, runs rembg (ONNX) "
        f"to produce a transparent PNG, uploads it to S3, and charges "
        f"{BG_REMOVAL_COST_COINS} AI-coin via BillingService. Returns ``cdn_url``."
    ),
)
async def remove_background_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BackgroundRemovalService, Depends(_get_bg_removal_service)],
    file: Annotated[
        UploadFile | None,
        File(description="Product image (JPEG/PNG/WebP)"),
    ] = None,
    image_url: Annotated[
        str | None,
        Form(
            description="Public HTTP(S) URL of the product image (alternative to file)",
            max_length=2048,
        ),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="X-Idempotency-Key",
            description="Optional durable billing idempotency key",
        ),
    ] = None,
) -> RemoveBgResponse:
    cleaned_key = idempotency_key.strip() if idempotency_key else None
    if cleaned_key == "":
        cleaned_key = None

    cleaned_url = image_url.strip() if image_url else None
    if cleaned_url == "":
        cleaned_url = None

    image_bytes: bytes | None = None
    if file is not None and file.filename:
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
            await file.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported content type: {content_type!r}.",
            )
        settings = get_settings()
        try:
            image_bytes = await _read_bounded_image(
                file,
                max_bytes=settings.security_max_upload_payload_bytes,
            )
        finally:
            await file.close()
    elif file is not None:
        await file.close()

    if image_bytes is None and cleaned_url is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide an image file or image_url.",
        )
    if image_bytes is not None and cleaned_url is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either an image file or image_url, not both.",
        )

    try:
        result = await service.process(
            user_id=current_user.id,
            image_bytes=image_bytes,
            image_url=cleaned_url,
            idempotency_key=cleaned_key,
        )
    except BackgroundRemovalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BackgroundRemovalEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except S3StorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        ) from exc
    except (BackgroundRemovalUpstreamError, S3StorageError) as exc:
        logger.exception("Background removal upstream failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BackgroundRemovalServiceError as exc:
        logger.exception("Background removal service failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return RemoveBgResponse(
        success=True,
        cdn_url=result.cdn_url,
        object_key=result.object_key,
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        width=result.width,
        height=result.height,
        content_type=result.content_type,
        cost_coins=BG_REMOVAL_COST_COINS,
    )
