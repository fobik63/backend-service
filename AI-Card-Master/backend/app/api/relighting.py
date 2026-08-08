"""REST API for managed photostudio relighting."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingNotFoundError, BillingValidationError
from app.services.relighting import (
    RELIGHTING_COST_COINS,
    RelightingEngineError,
    RelightingPresetName,
    RelightingService,
    RelightingServiceError,
    RelightingUpstreamError,
    RelightingValidationError,
)
from app.services.s3_storage import S3StorageConfigurationError, S3StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/relighting", tags=["relighting"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RelightProcessRequest(StrictAPIModel):
    image_url: str = Field(
        ...,
        min_length=8,
        max_length=2048,
        description="Public HTTP(S) URL of the product image",
    )
    preset_name: RelightingPresetName = Field(
        ...,
        description=(
            "Lighting preset: golden_hour | cyberpunk_neon | "
            "dramatic_studio | soft_commercial"
        ),
    )
    shadow_intensity: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Scales contact + cast shadow blur/opacity (0 = none, 1 = full)",
    )


class RelightProcessResponse(StrictAPIModel):
    success: bool = True
    result_url: str = Field(..., min_length=1)
    object_key: str = Field(..., min_length=1)
    preset_name: RelightingPresetName
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    content_type: str = "image/png"
    cost_coins: int = Field(default=RELIGHTING_COST_COINS, ge=0)


def _get_relighting_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> RelightingService:
    return RelightingService(db_session)


@router.post(
    "/process",
    response_model=RelightProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Relight a product image with a studio preset",
    description=(
        "Downloads ``image_url``, estimates depth/normal maps, applies a lighting "
        f"preset with contact+cast shadows, uploads the PNG to S3, and charges "
        f"{RELIGHTING_COST_COINS} AI-coins via BillingService."
    ),
)
async def process_relighting(
    body: RelightProcessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RelightingService, Depends(_get_relighting_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="X-Idempotency-Key",
            description="Optional durable billing idempotency key",
        ),
    ] = None,
) -> RelightProcessResponse:
    cleaned_key = idempotency_key.strip() if idempotency_key else None
    if cleaned_key == "":
        cleaned_key = None

    try:
        result = await service.process(
            user_id=current_user.id,
            image_url=str(body.image_url),
            preset_name=body.preset_name,
            shadow_intensity=body.shadow_intensity,
            idempotency_key=cleaned_key,
        )
    except RelightingValidationError as exc:
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
    except RelightingEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except S3StorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        ) from exc
    except (RelightingUpstreamError, S3StorageError) as exc:
        logger.exception("Relighting upstream failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except RelightingServiceError as exc:
        logger.exception("Relighting service failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return RelightProcessResponse(
        success=True,
        result_url=result.result_url,
        object_key=result.object_key,
        preset_name=result.preset_name,
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        width=result.width,
        height=result.height,
        content_type=result.content_type,
        cost_coins=RELIGHTING_COST_COINS,
    )


@router.get(
    "/presets",
    summary="List available lighting presets",
)
async def list_relighting_presets() -> dict[str, object]:
    from app.services.relighting.presets import LIGHTING_PRESETS

    return {
        "presets": [
            {
                "name": preset.name.value,
                "description": preset.description,
                "color_temperature_k": preset.color_temperature_k,
                "shadow_blur_px": preset.shadow_blur_px,
                "shadow_angle_deg": preset.shadow_angle_deg,
                "shadow_opacity": preset.shadow_opacity,
            }
            for preset in LIGHTING_PRESETS.values()
        ],
        "cost_coins": RELIGHTING_COST_COINS,
    }
