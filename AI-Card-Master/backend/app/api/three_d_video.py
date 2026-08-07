"""HTTP API for 360° orbital video render enqueue and status."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.three_d_video_service import (
    ThreeDVideoNotFoundError,
    ThreeDVideoValidationError,
)
from app.core.rate_limit import three_d_generate_limit
from app.domain.three_d_video import (
    DEFAULT_VIDEO_DURATION_SECONDS,
    DEFAULT_VIDEO_FPS,
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetView,
    VideoPresignedUrls,
    video_stage_label,
)
from app.infrastructure.celery_app import CELERY_THREE_D_HEAVY_QUEUE, celery_app
from app.infrastructure.three_d_video_factory import build_three_d_video_render_service
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.three_d.styles import (
    RenderSettingsDTO,
    ShadowCatcherFloorSettings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/3d/video", tags=["3D Video"])


class RenderSettingsBody(BaseModel):
    """JSON-friendly studio settings; coerces into strict ``RenderSettingsDTO``."""

    model_config = ConfigDict(extra="forbid")

    aspect_ratio: Literal["1:1", "3:4"] = "3:4"
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    long_side: int | None = Field(default=None, ge=64, le=8192)
    lighting_preset: str = "studio_soft"
    background_mode: str = "gradient"
    background_rgb: tuple[int, int, int] = (24, 28, 36)
    elevation_degrees: float = Field(default=20.0, ge=-80.0, le=80.0)
    fill_ratio: float = Field(default=0.825, ge=0.80, le=0.85)
    fov_degrees: float = Field(default=35.0, gt=5.0, lt=120.0)
    shadow_catcher: dict[str, Any] | None = None

    @field_validator("background_rgb", mode="before")
    @classmethod
    def _coerce_rgb(cls, value: object) -> object:
        if isinstance(value, list) and len(value) == 3:
            return (int(value[0]), int(value[1]), int(value[2]))
        return value

    def to_dto(self) -> RenderSettingsDTO:
        catcher: ShadowCatcherFloorSettings | None = None
        if self.shadow_catcher is not None:
            raw = dict(self.shadow_catcher)
            albedo = raw.get("albedo_rgb", (0.04, 0.04, 0.05))
            if isinstance(albedo, list):
                albedo = (float(albedo[0]), float(albedo[1]), float(albedo[2]))
            catcher = ShadowCatcherFloorSettings(
                enabled=bool(raw.get("enabled", True)),
                size_scale=float(raw.get("size_scale", 4.0)),
                y_offset=float(raw.get("y_offset", 0.02)),
                opacity=float(raw.get("opacity", 0.55)),
                shadow_softness=float(raw.get("shadow_softness", 0.65)),
                shadow_strength=float(raw.get("shadow_strength", 0.72)),
                receive_shadows=bool(raw.get("receive_shadows", True)),
                albedo_rgb=albedo,  # type: ignore[arg-type]
            )
        return RenderSettingsDTO.create(
            self.aspect_ratio,
            width=self.width,
            height=self.height,
            long_side=self.long_side,
            lighting_preset=self.lighting_preset,
            shadow_catcher=catcher,
            background_mode=self.background_mode,
            background_rgb=self.background_rgb,
            elevation_degrees=self.elevation_degrees,
            fill_ratio=self.fill_ratio,
            fov_degrees=self.fov_degrees,
        )


class VideoRenderRequest(BaseModel):
    """Enqueue body: source mesh task + studio ``RenderSettingsDTO``."""

    model_config = ConfigDict(extra="forbid")

    task_3d_id: UUID
    render_settings: RenderSettingsBody
    fps: int = Field(default=DEFAULT_VIDEO_FPS, ge=1, le=60)
    duration_seconds: float = Field(
        default=DEFAULT_VIDEO_DURATION_SECONDS, gt=0.5, le=30.0
    )
    rotation_direction: Literal["clockwise", "counter_clockwise"] = "clockwise"

    @field_validator("rotation_direction", mode="before")
    @classmethod
    def _normalise_rotation(cls, value: object) -> object:
        if isinstance(value, str):
            normalised = value.strip().lower().replace("-", "_")
            if normalised in {"cw", "clockwise"}:
                return "clockwise"
            if normalised in {
                "ccw",
                "counter_clockwise",
                "counterclockwise",
            }:
                return "counter_clockwise"
        return value

    def studio_settings(self) -> RenderSettingsDTO:
        """Materialise validated strict ``RenderSettingsDTO`` for the use-case."""

        return self.render_settings.to_dto()

class VideoRenderAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    video_task_id: UUID
    status: str = ThreeDVideoTaskStatus.QUEUED.value
    status_url: str
    ws_url: str
    celery_task_id: str | None = None
    cost_coins: int
    idempotent_replay: bool = False


class ThreeDVideoTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    video_task_id: UUID
    task_3d_id: UUID
    status: str
    resolution: str
    fps: int
    duration_seconds: float
    rotation_direction: str
    elevation_angle: float
    background_type: str
    cost_coins: int
    progress_percent: int
    stage: str | None = None
    stage_label: str | None = None
    celery_task_id: str | None = None
    error_detail: str | None = None
    execution_time_ms: int | None = None
    file_mp4_url: str | None = None
    file_webp_url: str | None = None
    file_gif_url: str | None = None
    width: int | None = None
    height: int | None = None
    file_size_bytes: int | None = None
    coins_held: bool = False
    coins_captured: bool = False
    coins_refunded: bool = False
    created_at: str
    updated_at: str


def get_three_d_video_svc(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
):
    return build_three_d_video_render_service(db_session)


def _to_response(
    task: ThreeDVideoTaskView,
    *,
    urls: VideoPresignedUrls | None = None,
    assets: VideoAssetView | None = None,
) -> ThreeDVideoTaskResponse:
    resolved_urls = urls or VideoPresignedUrls()
    return ThreeDVideoTaskResponse(
        video_task_id=task.id,
        task_3d_id=task.task_3d_id,
        status=task.status.value,
        resolution=task.resolution,
        fps=task.fps,
        duration_seconds=task.duration_seconds,
        rotation_direction=task.rotation_direction.value,
        elevation_angle=task.elevation_angle,
        background_type=task.background_type.value,
        cost_coins=task.cost_coins,
        progress_percent=task.progress_percent,
        stage=task.stage,
        stage_label=video_stage_label(task.stage),
        celery_task_id=task.celery_task_id,
        error_detail=task.error_detail,
        execution_time_ms=task.execution_time_ms,
        file_mp4_url=resolved_urls.mp4,
        file_webp_url=resolved_urls.webp,
        file_gif_url=resolved_urls.gif,
        width=assets.width if assets is not None else None,
        height=assets.height if assets is not None else None,
        file_size_bytes=assets.file_size_bytes if assets is not None else None,
        coins_held=task.coins_held,
        coins_captured=task.coins_captured,
        coins_refunded=task.coins_refunded,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


async def _enqueue_video_render(
    *,
    service: Any,
    current_user: User,
    body: VideoRenderRequest,
    idempotency_key: str | None,
) -> tuple[ThreeDVideoTaskView, str | None, bool]:
    try:
        task, replay = await service.create_render_task(
            user_id=current_user.id,
            task_3d_id=body.task_3d_id,
            ai_coins=int(current_user.ai_coins),
            render_settings=body.studio_settings(),
            fps=body.fps,
            duration_seconds=body.duration_seconds,
            rotation_direction=body.rotation_direction,
            idempotency_key=idempotency_key,
        )
    except ThreeDVideoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ThreeDVideoValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc

    celery_task_id = task.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "three_d.render_360_video_task",
            args=[str(task.id)],
            queue=CELERY_THREE_D_HEAVY_QUEUE,
        )
        celery_task_id = async_result.id
        task = await service.attach_celery_task(
            video_task_id=task.id,
            celery_task_id=celery_task_id,
        )
    return task, celery_task_id, replay


@router.post(
    "/render",
    response_model=VideoRenderAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a 360° orbital video render",
)
@three_d_generate_limit
async def render_three_d_video(
    request: Request,
    body: VideoRenderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_video_svc)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> VideoRenderAcceptedResponse:
    """Hold coins, create ``three_d_video_tasks`` row, enqueue Celery render."""

    _ = request  # required by slowapi
    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    task, celery_task_id, replay = await _enqueue_video_render(
        service=service,
        current_user=current_user,
        body=body,
        idempotency_key=idempotency_key,
    )
    return VideoRenderAcceptedResponse(
        video_task_id=task.id,
        status=task.status.value,
        status_url=f"/api/v1/3d/video/{task.id}",
        ws_url=f"/ws/v1/3d/video/{task.id}",
        celery_task_id=celery_task_id,
        cost_coins=task.cost_coins,
        idempotent_replay=replay,
    )


@router.get(
    "/{video_task_id}",
    response_model=ThreeDVideoTaskResponse,
    summary="Get 360° video task status and download URLs",
)
async def get_three_d_video_task(
    video_task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_video_svc)],
) -> ThreeDVideoTaskResponse:
    try:
        task, assets, urls = await service.get_result_for_user(
            video_task_id=video_task_id,
            user_id=current_user.id,
        )
    except ThreeDVideoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _to_response(task, urls=urls, assets=assets)
