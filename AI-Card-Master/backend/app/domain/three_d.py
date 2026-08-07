"""Domain types for 3D generation tasks, assets, and GPU rental sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ThreeDTaskStatus(StrEnum):
    """Persisted lifecycle of a 3D generation task."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


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


class ThreeDAssetFormat(StrEnum):
    """Supported binary formats stored for a 3D asset."""

    GLB = "glb"
    USDZ = "usdz"
    OBJ = "obj"
    PREVIEW_PNG = "preview_png"
    THUMBNAIL = "thumbnail"


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
    polycount_target: int | None
    texture_resolution: int | None
    error_message: str | None
    execution_time_seconds: float | None
    created_at: datetime
    updated_at: datetime


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
