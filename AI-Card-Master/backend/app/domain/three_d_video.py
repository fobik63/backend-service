"""Domain types for 360° orbital video generation tasks and stored assets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ThreeDVideoTaskStatus(StrEnum):
    """Persisted lifecycle of a 360° turntable video render job."""

    QUEUED = "QUEUED"
    RENDERING = "RENDERING"
    ENCODING = "ENCODING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_THREE_D_VIDEO_STATUSES: frozenset[ThreeDVideoTaskStatus] = frozenset(
    {
        ThreeDVideoTaskStatus.COMPLETED,
        ThreeDVideoTaskStatus.FAILED,
    }
)

# Celery hard/soft limits for ``render_360_video_task`` (OOM / runaway guard).
RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS = 180
RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS = 150
# Publish Redis progress at most every N frames during orbit rasterisation.
RENDER_360_VIDEO_PROGRESS_FRAME_INTERVAL = 10
# Cap concurrent render jobs per ``worker-three-d`` process.
RENDER_360_VIDEO_WORKER_CONCURRENCY = 2

REDIS_THREE_D_VIDEO_PROGRESS_TTL_SECONDS = 3600
REDIS_THREE_D_VIDEO_PROGRESS_PREFIX = "three_d:video:progress"
REDIS_THREE_D_VIDEO_PROGRESS_CHANNEL_PREFIX = "three_d:video:progress:channel"

_VIDEO_STAGE_LABELS: dict[str, str] = {
    "queued": "в очереди",
    "loading_mesh": "загрузка модели",
    "rendering_frames": "рендер кадров",
    "encoding": "кодирование видео",
    "uploading": "загрузка в хранилище",
    "finalizing": "финализация",
    "failed": "ошибка",
}


def redis_three_d_video_progress_key(video_task_id: UUID) -> str:
    """Redis JSON key for the latest 360° video progress snapshot."""

    return f"{REDIS_THREE_D_VIDEO_PROGRESS_PREFIX}:{video_task_id}"


def redis_three_d_video_progress_channel(video_task_id: UUID) -> str:
    """Pub/sub channel for live 360° video progress fan-out."""

    return f"{REDIS_THREE_D_VIDEO_PROGRESS_CHANNEL_PREFIX}:{video_task_id}"


def video_stage_label(stage: str | None) -> str | None:
    """Human-readable Russian stage label for Redis / WebSocket payloads."""

    if stage is None or not str(stage).strip():
        return None
    value = str(stage).strip()
    return _VIDEO_STAGE_LABELS.get(value, value)


class VideoBackgroundType(StrEnum):
    """Backdrop style used while orbiting the mesh."""

    TRANSPARENT = "TRANSPARENT"
    GRADIENT = "GRADIENT"
    SOLID_COLOR = "SOLID_COLOR"
    STUDIO_LIGHT = "STUDIO_LIGHT"


class VideoRotationDirection(StrEnum):
    """Orbit direction around the vertical axis."""

    CLOCKWISE = "clockwise"
    COUNTER_CLOCKWISE = "counter_clockwise"


class VideoAssetFormat(StrEnum):
    """Downloadable container formats produced by the render pipeline."""

    MP4 = "mp4"
    WEBP = "webp"
    GIF = "gif"


VIDEO_CONTENT_TYPES: dict[VideoAssetFormat, str] = {
    VideoAssetFormat.MP4: "video/mp4",
    VideoAssetFormat.WEBP: "image/webp",
    VideoAssetFormat.GIF: "image/gif",
}

VIDEO_FILE_EXTENSIONS: dict[VideoAssetFormat, str] = {
    VideoAssetFormat.MP4: "mp4",
    VideoAssetFormat.WEBP: "webp",
    VideoAssetFormat.GIF: "gif",
}

# One year — immutable content-addressed / UUID-keyed objects.
VIDEO_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
VIDEO_ASSET_CACHE_MAX_AGE_SECONDS = 31_536_000

DEFAULT_VIDEO_FPS = 24
DEFAULT_VIDEO_DURATION_SECONDS = 5.0
DEFAULT_VIDEO_ELEVATION_ANGLE = 15.0
DEFAULT_VIDEO_RESOLUTION = "1080x1440"


def parse_rotation_direction(raw: str | None) -> VideoRotationDirection:
    """Normalise API rotation onto the domain enum."""

    if raw is None or not str(raw).strip():
        return VideoRotationDirection.CLOCKWISE
    normalised = str(raw).strip().lower().replace("-", "_")
    if normalised in {"cw", "clockwise"}:
        return VideoRotationDirection.CLOCKWISE
    if normalised in {"ccw", "counter_clockwise", "counterclockwise", "counter-clockwise"}:
        return VideoRotationDirection.COUNTER_CLOCKWISE
    try:
        return VideoRotationDirection(normalised)
    except ValueError as exc:
        raise ValueError(f"Unsupported rotation_direction: {raw!r}") from exc


def parse_background_type(raw: str | None) -> VideoBackgroundType:
    """Normalise API background onto the domain enum."""

    if raw is None or not str(raw).strip():
        return VideoBackgroundType.STUDIO_LIGHT
    normalised = str(raw).strip().upper()
    try:
        return VideoBackgroundType(normalised)
    except ValueError as exc:
        raise ValueError(f"Unsupported background_type: {raw!r}") from exc


def parse_resolution(raw: str | None) -> str:
    """Validate ``WIDTHxHEIGHT`` resolution strings (e.g. ``1080x1440``)."""

    value = (raw or DEFAULT_VIDEO_RESOLUTION).strip().lower()
    parts = value.split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid resolution (expected WIDTHxHEIGHT): {raw!r}")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid resolution (expected WIDTHxHEIGHT): {raw!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Resolution dimensions must be positive: {raw!r}")
    return f"{width}x{height}"


@dataclass(frozen=True, slots=True)
class ThreeDVideoTaskView:
    """Projection of a persisted 360° video generation task."""

    id: UUID
    task_3d_id: UUID
    user_id: UUID
    status: ThreeDVideoTaskStatus
    resolution: str
    fps: int
    duration_seconds: float
    rotation_direction: VideoRotationDirection
    elevation_angle: float
    background_type: VideoBackgroundType
    error_detail: str | None
    execution_time_ms: int | None
    created_at: datetime
    updated_at: datetime
    cost_coins: int = 0
    progress_percent: int = 0
    stage: str | None = None
    celery_task_id: str | None = None
    coins_held: bool = False
    coins_captured: bool = False
    coins_refunded: bool = False
    coin_hold_id: UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ThreeDVideoProgressSnapshot:
    """Live progress payload mirrored in Redis during Celery video render.

    Compact shape for polling clients::

        {"stage": "rendering_frames", "progress": 45}
    """

    video_task_id: UUID
    status: ThreeDVideoTaskStatus
    stage: str
    progress: int
    stage_label: str | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_task_id": str(self.video_task_id),
            "status": self.status.value,
            "stage": self.stage,
            "progress": int(self.progress),
            "stage_label": self.stage_label,
            "error_detail": self.error_detail,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ThreeDVideoProgressSnapshot:
        return cls(
            video_task_id=UUID(str(payload["video_task_id"])),
            status=ThreeDVideoTaskStatus(str(payload["status"])),
            stage=str(payload.get("stage") or "queued"),
            progress=int(payload.get("progress") or 0),
            stage_label=(
                str(payload["stage_label"]) if payload.get("stage_label") else None
            ),
            error_detail=(
                str(payload["error_detail"]) if payload.get("error_detail") else None
            ),
        )

    @classmethod
    def from_task_view(cls, task: ThreeDVideoTaskView) -> ThreeDVideoProgressSnapshot:
        stage = task.stage or "queued"
        return cls(
            video_task_id=task.id,
            status=task.status,
            stage=stage,
            progress=int(task.progress_percent),
            stage_label=video_stage_label(stage),
            error_detail=task.error_detail,
        )


@dataclass(frozen=True, slots=True)
class VideoAssetView:
    """Projection of stored MP4 / WebP / GIF outputs for one video task."""

    id: UUID
    video_task_id: UUID
    user_id: UUID
    file_mp4_url: str | None
    file_webp_url: str | None
    file_gif_url: str | None
    file_size_bytes: int | None
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class VideoUploadResult:
    """Outcome of uploading one video asset format to object storage."""

    format: VideoAssetFormat
    object_key: str
    content_type: str
    size_bytes: int
    presigned_url: str
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class VideoPresignedUrls:
    """Temporary GET URLs for frontend consumption of a video asset set."""

    mp4: str | None = None
    webp: str | None = None
    gif: str | None = None
