"""Application ports for 3D generation persistence and progress fan-out."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.domain.three_d import (
    GpuRentalSessionStatus,
    GpuRentalSessionView,
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDOutputFormat,
    ThreeDProgressSnapshot,
    ThreeDTaskStatus,
    ThreeDTaskView,
)


class ThreeDPersistencePort(Protocol):
    """Durable store for 3D tasks and result assets."""

    async def create_task(
        self,
        *,
        user_id: UUID,
        input_type: ThreeDInputType,
        prompt: str | None,
        source_image_url: str | None,
        provider_name: str,
        cost_coins: int,
        polycount_target: int | None,
        texture_resolution: int | None,
        output_format: ThreeDOutputFormat | None = None,
        idempotency_key: str | None = None,
    ) -> ThreeDTaskView: ...

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDTaskView | None: ...

    async def get_task(self, task_id: UUID) -> ThreeDTaskView | None: ...

    async def get_task_for_user(
        self, *, task_id: UUID, user_id: UUID
    ) -> ThreeDTaskView | None: ...

    async def attach_celery_task(
        self, *, task_id: UUID, celery_task_id: str
    ) -> ThreeDTaskView: ...

    async def hold_coins(self, *, task_id: UUID) -> ThreeDTaskView: ...

    async def capture_held_coins(self, *, task_id: UUID) -> ThreeDTaskView: ...

    async def release_held_coins(self, *, task_id: UUID) -> ThreeDTaskView: ...

    async def mark_provider_submitted(
        self,
        *,
        task_id: UUID,
        provider_job_id: str,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
    ) -> ThreeDTaskView: ...

    async def update_progress(
        self,
        *,
        task_id: UUID,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
        error_message: str | None = None,
        provider_job_id: str | None = None,
    ) -> ThreeDTaskView: ...

    async def mark_failed(
        self,
        *,
        task_id: UUID,
        error_message: str,
        release_coins: bool = True,
    ) -> ThreeDTaskView: ...

    async def complete_with_assets(
        self,
        *,
        task_id: UUID,
        file_glb_url: str | None,
        file_usdz_url: str | None,
        file_obj_url: str | None,
        preview_png_url: str | None,
        thumbnail_url: str | None,
        polycount_actual: int | None,
        file_size_bytes: int | None,
        execution_time_seconds: float | None,
    ) -> tuple[ThreeDTaskView, ThreeDAssetView]: ...

    async def get_asset_for_task(self, task_id: UUID) -> ThreeDAssetView | None: ...

    async def list_assets_for_user(
        self, *, user_id: UUID, limit: int, offset: int
    ) -> tuple[tuple[ThreeDAssetView, ...], int]: ...

    async def list_active_task_ids(self, *, limit: int) -> tuple[UUID, ...]: ...

    async def get_by_provider_job_id(
        self, *, provider_name: str, provider_job_id: str
    ) -> ThreeDTaskView | None: ...

    async def get_active_gpu_rental(
        self, *, user_id: UUID
    ) -> GpuRentalSessionView | None: ...

    async def create_gpu_rental(
        self,
        *,
        user_id: UUID,
        provider_name: str,
        instance_type: str,
        hourly_rate_coins: int,
    ) -> GpuRentalSessionView: ...

    async def get_gpu_rental_for_user(
        self, *, session_id: UUID, user_id: UUID
    ) -> GpuRentalSessionView | None: ...

    async def stop_gpu_rental(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        total_cost_coins: int,
        debit_coins: bool = True,
        status: GpuRentalSessionStatus = GpuRentalSessionStatus.STOPPED,
    ) -> GpuRentalSessionView: ...


class ThreeDProgressCachePort(Protocol):
    """Redis mirror + pub/sub for live 3D progress."""

    async def publish(self, snapshot: ThreeDProgressSnapshot) -> None: ...

    async def get(self, task_id: UUID) -> ThreeDProgressSnapshot | None: ...

    async def subscribe_payloads(
        self, task_id: UUID
    ) -> Any: ...  # async iterator of dict payloads
