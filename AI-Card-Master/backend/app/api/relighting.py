"""REST API for managed photostudio relighting."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
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
    StudioLightDTO,
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


class RelightCustomRequest(StrictAPIModel):
    image_url: str = Field(
        ...,
        min_length=8,
        max_length=2048,
        description="Public HTTP(S) URL of the product image",
    )
    studio_light: StudioLightDTO = Field(
        ...,
        description=(
            "Parametric softbox: light_angle, light_elevation, "
            "color_temp_k, intensity, softbox_diffusion"
        ),
    )


class RelightParseInstructionRequest(StrictAPIModel):
    instruction: str = Field(
        ...,
        min_length=2,
        max_length=512,
        description='Natural-language cue, e.g. "мягкий тёплый свет слева сверху"',
    )


class RelightProcessResponse(StrictAPIModel):
    success: bool = True
    result_url: str = Field(..., min_length=1)
    object_key: str = Field(..., min_length=1)
    preset_name: RelightingPresetName | None = None
    studio_light: StudioLightDTO | None = None
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    content_type: str = "image/png"
    cost_coins: int = Field(default=RELIGHTING_COST_COINS, ge=0)


class RelightParseInstructionResponse(StrictAPIModel):
    success: bool = True
    studio_light: StudioLightDTO
    instruction: str = Field(..., min_length=1)


def _get_relighting_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> RelightingService:
    return RelightingService(db_session)


def _map_relighting_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RelightingValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, BillingValidationError):
        return HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        )
    if isinstance(exc, BillingNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RelightingEngineError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, S3StorageConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        )
    if isinstance(exc, (RelightingUpstreamError, S3StorageError)):
        logger.exception("Relighting upstream failure")
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, RelightingServiceError):
        logger.exception("Relighting service failure")
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    raise exc


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
    except Exception as exc:
        mapped = _map_relighting_http_error(exc)
        raise mapped from exc

    return RelightProcessResponse(
        success=True,
        result_url=result.result_url,
        object_key=result.object_key,
        preset_name=result.preset_name,
        studio_light=result.studio_light,
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        width=result.width,
        height=result.height,
        content_type=result.content_type,
        cost_coins=RELIGHTING_COST_COINS,
    )


@router.post(
    "/custom",
    response_model=RelightProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Relight with a parametric softbox (StudioLightDTO)",
    description=(
        "Downloads ``image_url``, applies a parametric softbox "
        "(angle / elevation / color temperature / intensity / diffusion) with a "
        "soft contact shadow opposite the key, uploads PNG to S3, and charges "
        f"{RELIGHTING_COST_COINS} AI-coins."
    ),
)
async def process_custom_relighting(
    body: RelightCustomRequest,
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
        result = await service.process_custom(
            user_id=current_user.id,
            image_url=str(body.image_url),
            studio_light=body.studio_light,
            idempotency_key=cleaned_key,
        )
    except Exception as exc:
        mapped = _map_relighting_http_error(exc)
        raise mapped from exc

    return RelightProcessResponse(
        success=True,
        result_url=result.result_url,
        object_key=result.object_key,
        preset_name=result.preset_name,
        studio_light=result.studio_light,
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        width=result.width,
        height=result.height,
        content_type=result.content_type,
        cost_coins=RELIGHTING_COST_COINS,
    )


@router.post(
    "/parse-instruction",
    response_model=RelightParseInstructionResponse,
    status_code=status.HTTP_200_OK,
    summary="Convert a lighting phrase into StudioLightDTO",
    description=(
        'Maps cues like "мягкий тёплый свет слева сверху" to parametric '
        "softbox fields (no billing)."
    ),
)
async def parse_relighting_instruction(
    body: RelightParseInstructionRequest,
) -> RelightParseInstructionResponse:
    try:
        studio_light = RelightingService.parse_instruction(body.instruction)
    except RelightingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return RelightParseInstructionResponse(
        success=True,
        studio_light=studio_light,
        instruction=body.instruction.strip(),
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
        "studio_light_params": {
            "light_angle": {"min": 0.0, "max": 360.0, "unit": "deg"},
            "light_elevation": {"min": 10.0, "max": 90.0, "unit": "deg"},
            "color_temp_k": {"min": 2700, "max": 7500, "unit": "K"},
            "intensity": {"min": 0.0, "max": 2.0},
            "softbox_diffusion": {"min": 0.0, "max": 1.0},
        },
    }
