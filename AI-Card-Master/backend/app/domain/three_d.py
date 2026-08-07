"""Domain types for 3D generation tasks, assets, and GPU rental sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ThreeDTaskStatus(StrEnum):
    """Persisted lifecycle of a 3D generation task."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


TERMINAL_THREE_D_STATUSES: frozenset[ThreeDTaskStatus] = frozenset(
    {
        ThreeDTaskStatus.COMPLETED,
        ThreeDTaskStatus.FAILED,
        ThreeDTaskStatus.CANCELED,
    }
)

REDIS_THREE_D_PROGRESS_TTL_SECONDS = 3600
REDIS_THREE_D_PROGRESS_PREFIX = "three_d:progress"
REDIS_THREE_D_PROGRESS_CHANNEL_PREFIX = "three_d:progress:channel"

_PROVIDER_STATUS_MAP: dict[str, ThreeDTaskStatus] = {
    "QUEUED": ThreeDTaskStatus.PENDING,
    "PROCESSING": ThreeDTaskStatus.PROCESSING,
    "COMPLETED": ThreeDTaskStatus.COMPLETED,
    "FAILED": ThreeDTaskStatus.FAILED,
}

_STAGE_LABELS: dict[str, str] = {
    "drafting_mesh": "генерация сетки",
    "generating_textures": "текстурирование",
    "baking_maps": "запекание карт",
}


def redis_three_d_progress_key(task_id: UUID) -> str:
    """Redis JSON key holding the latest progress snapshot for ``task_id``."""

    return f"{REDIS_THREE_D_PROGRESS_PREFIX}:{task_id}"


def redis_three_d_progress_channel(task_id: UUID) -> str:
    """Pub/sub channel that WebSocket clients subscribe to for live updates."""

    return f"{REDIS_THREE_D_PROGRESS_CHANNEL_PREFIX}:{task_id}"


def map_provider_status_to_domain(status: str) -> ThreeDTaskStatus:
    """Map provider DTO lifecycle onto persisted domain status."""

    normalised = str(status).strip().upper()
    mapped = _PROVIDER_STATUS_MAP.get(normalised)
    if mapped is None:
        raise ValueError(f"Unknown provider 3D status: {status!r}")
    return mapped


def stage_label(stage: str | None) -> str | None:
    """Human-readable Russian stage label for WebSocket / Redis payloads."""

    if stage is None or not str(stage).strip():
        return None
    value = str(stage).strip()
    return _STAGE_LABELS.get(value, value)


class ThreeDInputType(StrEnum):
    """How the user requested the 3D model."""

    TEXT_TO_3D = "TEXT_TO_3D"
    IMAGE_TO_3D = "IMAGE_TO_3D"


class GpuRentalSessionStatus(StrEnum):
    """Lifecycle of a reserved GPU rental session."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    TERMINATED = "TERMINATED"


class ThreeDOutputFormat(StrEnum):
    """Preferred downloadable mesh format requested at generate time."""

    GLB = "GLB"
    USDZ = "USDZ"


class ThreeDAssetFormat(StrEnum):
    """Supported binary formats stored for a 3D asset."""

    GLB = "glb"
    USDZ = "usdz"
    OBJ = "obj"
    PREVIEW_PNG = "preview_png"
    THUMBNAIL = "thumbnail"


def parse_output_format(raw: str | None) -> ThreeDOutputFormat:
    """Normalise API ``format`` (GLB/USDZ) onto the domain enum."""

    if raw is None or not str(raw).strip():
        return ThreeDOutputFormat.GLB
    normalised = str(raw).strip().upper()
    try:
        return ThreeDOutputFormat(normalised)
    except ValueError as exc:
        raise ValueError(f"Unsupported 3D output format: {raw!r}") from exc


def output_format_to_asset(fmt: ThreeDOutputFormat) -> ThreeDAssetFormat:
    """Map preferred output format onto the storage asset enum."""

    if fmt is ThreeDOutputFormat.USDZ:
        return ThreeDAssetFormat.USDZ
    return ThreeDAssetFormat.GLB


THREE_D_CONTENT_TYPES: dict[ThreeDAssetFormat, str] = {
    ThreeDAssetFormat.GLB: "model/gltf-binary",
    ThreeDAssetFormat.USDZ: "model/vnd.usdz+zip",
    ThreeDAssetFormat.OBJ: "model/obj",
    ThreeDAssetFormat.PREVIEW_PNG: "image/png",
    ThreeDAssetFormat.THUMBNAIL: "image/png",
}

THREE_D_FILE_EXTENSIONS: dict[ThreeDAssetFormat, str] = {
    ThreeDAssetFormat.GLB: "glb",
    ThreeDAssetFormat.USDZ: "usdz",
    ThreeDAssetFormat.OBJ: "obj",
    ThreeDAssetFormat.PREVIEW_PNG: "png",
    ThreeDAssetFormat.THUMBNAIL: "png",
}


@dataclass(frozen=True, slots=True)
class ThreeDTaskView:
    """Projection of a persisted 3D generation task."""

    id: UUID
    user_id: UUID
    status: ThreeDTaskStatus
    input_type: ThreeDInputType
    prompt: str | None
    source_image_url: str | None
    provider_name: str | None
    provider_job_id: str | None
    cost_coins: int
    progress_percent: int
    stage: str | None
    celery_task_id: str | None
    coins_held: bool
    coins_captured: bool
    coins_refunded: bool
    polycount_target: int | None
    texture_resolution: int | None
    output_format: ThreeDOutputFormat | None
    idempotency_key: str | None
    error_message: str | None
    execution_time_seconds: float | None
    created_at: datetime
    updated_at: datetime
    coin_hold_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ThreeDProgressSnapshot:
    """Live progress payload mirrored in Redis and pushed over WebSocket."""

    task_id: UUID
    status: ThreeDTaskStatus
    progress_percent: int
    stage: str | None
    stage_label: str | None
    error_message: str | None = None
    provider_job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "status": self.status.value,
            "progress_percent": self.progress_percent,
            "stage": self.stage,
            "stage_label": self.stage_label,
            "error_message": self.error_message,
            "provider_job_id": self.provider_job_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ThreeDProgressSnapshot:
        return cls(
            task_id=UUID(str(payload["task_id"])),
            status=ThreeDTaskStatus(str(payload["status"])),
            progress_percent=int(payload.get("progress_percent") or 0),
            stage=(str(payload["stage"]) if payload.get("stage") else None),
            stage_label=(
                str(payload["stage_label"]) if payload.get("stage_label") else None
            ),
            error_message=(
                str(payload["error_message"]) if payload.get("error_message") else None
            ),
            provider_job_id=(
                str(payload["provider_job_id"])
                if payload.get("provider_job_id")
                else None
            ),
        )

    @classmethod
    def from_task_view(cls, task: ThreeDTaskView) -> ThreeDProgressSnapshot:
        return cls(
            task_id=task.id,
            status=task.status,
            progress_percent=task.progress_percent,
            stage=task.stage,
            stage_label=stage_label(task.stage),
            error_message=task.error_message,
            provider_job_id=task.provider_job_id,
        )


@dataclass(frozen=True, slots=True)
class ThreeDAssetView:
    """Projection of stored 3D result files for one task."""

    id: UUID
    task_id: UUID
    user_id: UUID
    file_glb_url: str | None
    file_usdz_url: str | None
    file_obj_url: str | None
    preview_png_url: str | None
    thumbnail_url: str | None
    polycount_actual: int | None
    file_size_bytes: int | None


@dataclass(frozen=True, slots=True)
class GpuRentalSessionView:
    """Projection of a GPU rental reservation (future feature)."""

    id: UUID
    user_id: UUID
    provider_name: str
    instance_type: str
    status: GpuRentalSessionStatus
    hourly_rate_coins: int
    started_at: datetime | None
    stopped_at: datetime | None
    total_cost_coins: int


@dataclass(frozen=True, slots=True)
class ThreeDUploadResult:
    """Outcome of uploading one 3D asset format to object storage."""

    format: ThreeDAssetFormat
    object_key: str
    content_type: str
    size_bytes: int
    presigned_url: str
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class ThreeDPresignedUrls:
    """Temporary GET URLs for frontend consumption of a stored asset set."""

    glb: str | None = None
    usdz: str | None = None
    obj: str | None = None
    preview_png: str | None = None
    thumbnail: str | None = None
