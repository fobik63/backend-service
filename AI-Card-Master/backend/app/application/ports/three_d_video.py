"""Application port for 360° video task / asset persistence."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.three_d_video import (
    ThreeDVideoProgressSnapshot,
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetView,
    VideoBackgroundType,
    VideoRotationDirection,
)


class ThreeDVideoPersistencePort(Protocol):
    """Durable store for ``three_d_video_tasks`` and ``video_assets``."""

    async def create_task(
        self,
        *,
        task_3d_id: UUID,
        user_id: UUID,
        resolution: str = "1080x1440",
        fps: int = 24,
        duration_seconds: float = 5.0,
        rotation_direction: VideoRotationDirection = VideoRotationDirection.CLOCKWISE,
        elevation_angle: float = 15.0,
        background_type: VideoBackgroundType = VideoBackgroundType.STUDIO_LIGHT,
        status: ThreeDVideoTaskStatus = ThreeDVideoTaskStatus.QUEUED,
        cost_coins: int = 0,
        idempotency_key: str | None = None,
    ) -> ThreeDVideoTaskView: ...

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDVideoTaskView | None: ...

    async def get_task(self, video_task_id: UUID) -> ThreeDVideoTaskView | None: ...

    async def get_task_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> ThreeDVideoTaskView | None: ...

    async def list_tasks_for_3d(
        self, *, task_3d_id: UUID, user_id: UUID
    ) -> list[ThreeDVideoTaskView]: ...

    async def attach_celery_task(
        self, *, video_task_id: UUID, celery_task_id: str
    ) -> ThreeDVideoTaskView: ...

    async def hold_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView: ...

    async def capture_held_coins(
        self, *, video_task_id: UUID
    ) -> ThreeDVideoTaskView: ...

    async def release_held_coins(
        self, *, video_task_id: UUID
    ) -> ThreeDVideoTaskView: ...

    async def update_progress(
        self,
        *,
        video_task_id: UUID,
        status: ThreeDVideoTaskStatus,
        progress_percent: int,
        stage: str | None,
        error_detail: str | None = None,
    ) -> ThreeDVideoTaskView: ...

    async def update_status(
        self,
        *,
        video_task_id: UUID,
        status: ThreeDVideoTaskStatus,
        error_detail: str | None = None,
        execution_time_ms: int | None = None,
    ) -> ThreeDVideoTaskView: ...

    async def mark_failed(
        self, *, video_task_id: UUID, error_detail: str
    ) -> ThreeDVideoTaskView: ...

    async def mark_completed(
        self, *, video_task_id: UUID, execution_time_ms: int | None = None
    ) -> ThreeDVideoTaskView: ...

    async def upsert_assets(
        self,
        *,
        video_task_id: UUID,
        user_id: UUID,
        file_mp4_url: str | None = None,
        file_webp_url: str | None = None,
        file_gif_url: str | None = None,
        file_size_bytes: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> VideoAssetView: ...

    async def get_assets(
        self, *, video_task_id: UUID
    ) -> VideoAssetView | None: ...

    async def get_assets_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> VideoAssetView | None: ...


class ThreeDVideoProgressCachePort(Protocol):
    """Redis mirror for live 360° video render progress."""

    async def publish(self, snapshot: ThreeDVideoProgressSnapshot) -> None: ...

    async def get(
        self, video_task_id: UUID
    ) -> ThreeDVideoProgressSnapshot | None: ...
