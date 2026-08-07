"""SQLAlchemy persistence for 360° video tasks and video_assets."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pricing import (
    BillingService as OperationBillingService,
)
from app.core.pricing import (
    CoinHoldStatus,
    PricingNotFoundError,
)
from app.domain.three_d_video import (
    DEFAULT_VIDEO_DURATION_SECONDS,
    DEFAULT_VIDEO_ELEVATION_ANGLE,
    DEFAULT_VIDEO_FPS,
    DEFAULT_VIDEO_RESOLUTION,
    TERMINAL_THREE_D_VIDEO_STATUSES,
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetView,
    VideoBackgroundType,
    VideoRotationDirection,
    parse_resolution,
)
from app.models.three_d import ThreeDVideoTask, VideoAsset
from app.services.billing_service import (
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)


def _task_view(row: ThreeDVideoTask) -> ThreeDVideoTaskView:
    return ThreeDVideoTaskView(
        id=row.id,
        task_3d_id=row.task_3d_id,
        user_id=row.user_id,
        status=ThreeDVideoTaskStatus(row.status),
        resolution=row.resolution,
        fps=int(row.fps),
        duration_seconds=float(row.duration_seconds),
        rotation_direction=VideoRotationDirection(row.rotation_direction),
        elevation_angle=float(row.elevation_angle),
        background_type=VideoBackgroundType(row.background_type),
        error_detail=row.error_detail,
        execution_time_ms=row.execution_time_ms,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cost_coins=int(row.cost_coins or 0),
        progress_percent=int(row.progress_percent or 0),
        stage=row.stage,
        celery_task_id=row.celery_task_id,
        coins_held=bool(row.coins_held),
        coins_captured=bool(row.coins_captured),
        coins_refunded=bool(row.coins_refunded),
        coin_hold_id=row.coin_hold_id,
        idempotency_key=row.idempotency_key,
        studio_settings=(
            dict(row.studio_settings) if isinstance(row.studio_settings, dict) else None
        ),
    )


def _asset_view(row: VideoAsset) -> VideoAssetView:
    return VideoAssetView(
        id=row.id,
        video_task_id=row.video_task_id,
        user_id=row.user_id,
        file_mp4_url=row.file_mp4_url,
        file_webp_url=row.file_webp_url,
        file_gif_url=row.file_gif_url,
        file_size_bytes=row.file_size_bytes,
        width=row.width,
        height=row.height,
    )


class ThreeDVideoRepository:
    """Unit-of-work repository for ``three_d_video_tasks`` / ``video_assets``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _locked_task(self, video_task_id: UUID) -> ThreeDVideoTask:
        stmt = (
            select(ThreeDVideoTask)
            .where(ThreeDVideoTask.id == video_task_id)
            .with_for_update()
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise LookupError(f"three_d_video_task not found: {video_task_id}")
        return row

    async def create_task(
        self,
        *,
        task_3d_id: UUID,
        user_id: UUID,
        resolution: str = DEFAULT_VIDEO_RESOLUTION,
        fps: int = DEFAULT_VIDEO_FPS,
        duration_seconds: float = DEFAULT_VIDEO_DURATION_SECONDS,
        rotation_direction: VideoRotationDirection = VideoRotationDirection.CLOCKWISE,
        elevation_angle: float = DEFAULT_VIDEO_ELEVATION_ANGLE,
        background_type: VideoBackgroundType = VideoBackgroundType.STUDIO_LIGHT,
        status: ThreeDVideoTaskStatus = ThreeDVideoTaskStatus.QUEUED,
        cost_coins: int = 0,
        idempotency_key: str | None = None,
        studio_settings: dict | None = None,
    ) -> ThreeDVideoTaskView:
        resolved = parse_resolution(resolution)
        if fps <= 0:
            raise ValueError("fps must be positive.")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive.")
        if cost_coins < 0:
            raise ValueError("cost_coins must be non-negative.")

        row = ThreeDVideoTask(
            task_3d_id=task_3d_id,
            user_id=user_id,
            status=status.value,
            resolution=resolved,
            fps=int(fps),
            duration_seconds=float(duration_seconds),
            rotation_direction=rotation_direction.value,
            elevation_angle=float(elevation_angle),
            background_type=background_type.value,
            cost_coins=int(cost_coins),
            progress_percent=0,
            stage="queued",
            idempotency_key=idempotency_key,
            studio_settings=dict(studio_settings) if studio_settings else None,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDVideoTaskView | None:
        key = idempotency_key.strip()
        if not key:
            return None
        stmt = select(ThreeDVideoTask).where(
            ThreeDVideoTask.user_id == user_id,
            ThreeDVideoTask.idempotency_key == key,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _task_view(row) if row is not None else None

    async def get_task(self, video_task_id: UUID) -> ThreeDVideoTaskView | None:
        row = await self._session.get(ThreeDVideoTask, video_task_id)
        return _task_view(row) if row is not None else None

    async def get_task_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> ThreeDVideoTaskView | None:
        stmt = select(ThreeDVideoTask).where(
            ThreeDVideoTask.id == video_task_id,
            ThreeDVideoTask.user_id == user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _task_view(row) if row is not None else None

    async def list_tasks_for_3d(
        self, *, task_3d_id: UUID, user_id: UUID
    ) -> list[ThreeDVideoTaskView]:
        stmt = (
            select(ThreeDVideoTask)
            .where(
                ThreeDVideoTask.task_3d_id == task_3d_id,
                ThreeDVideoTask.user_id == user_id,
            )
            .order_by(ThreeDVideoTask.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_task_view(row) for row in rows]

    async def attach_celery_task(
        self, *, video_task_id: UUID, celery_task_id: str
    ) -> ThreeDVideoTaskView:
        row = await self._locked_task(video_task_id)
        row.celery_task_id = celery_task_id[:255]
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def hold_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        """Freeze ``cost_coins`` via the Safe-Spend ``coin_holds`` ledger."""

        row = await self._locked_task(video_task_id)
        if row.coins_held or row.coins_captured:
            return _task_view(row)
        amount = int(row.cost_coins)
        billing = OperationBillingService(self._session)
        try:
            hold_id = await billing.hold_coins(
                row.user_id,
                amount,
                service_type="three_d_video",
                reference_id=row.id,
                idempotency_key=(
                    f"three_d_video:{row.idempotency_key}"
                    if row.idempotency_key
                    else f"three_d_video_hold:{row.id}"
                ),
                commit=False,
            )
        except BillingNotFoundError as exc:
            raise LookupError("User was not found.") from exc
        except BillingValidationError:
            raise
        row.coin_hold_id = hold_id
        row.coins_held = True
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def capture_held_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        """Convert a hold into a final charge (balance already debited)."""

        row = await self._locked_task(video_task_id)
        if row.coins_captured:
            return _task_view(row)
        if row.coin_hold_id is not None:
            try:
                await OperationBillingService(self._session).commit_or_refund(
                    row.coin_hold_id,
                    True,
                    commit=False,
                )
            except PricingNotFoundError:
                pass
        row.coins_held = False
        row.coins_captured = True
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def release_held_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        """Unfreeze held coins by refunding the debit (OOM / failure path)."""

        row = await self._locked_task(video_task_id)
        if row.coins_refunded or row.coins_captured:
            return _task_view(row)
        if row.coin_hold_id is not None and row.coins_held:
            try:
                status = await OperationBillingService(self._session).commit_or_refund(
                    row.coin_hold_id,
                    False,
                    commit=False,
                )
                if status is not CoinHoldStatus.REFUNDED and int(row.cost_coins) > 0:
                    try:
                        await BillingService(self._session).refund_coins_in_transaction(
                            user_id=row.user_id,
                            amount=int(row.cost_coins),
                        )
                    except BillingNotFoundError as exc:
                        raise LookupError("User was not found.") from exc
            except PricingNotFoundError:
                amount = int(row.cost_coins) if row.coins_held else 0
                if amount > 0:
                    try:
                        await BillingService(self._session).refund_coins_in_transaction(
                            user_id=row.user_id,
                            amount=amount,
                        )
                    except BillingNotFoundError as exc:
                        raise LookupError("User was not found.") from exc
        elif row.coins_held:
            amount = int(row.cost_coins)
            if amount > 0:
                try:
                    await BillingService(self._session).refund_coins_in_transaction(
                        user_id=row.user_id,
                        amount=amount,
                    )
                except BillingNotFoundError as exc:
                    raise LookupError("User was not found.") from exc
        row.coins_held = False
        row.coins_refunded = True
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def update_progress(
        self,
        *,
        video_task_id: UUID,
        status: ThreeDVideoTaskStatus,
        progress_percent: int,
        stage: str | None,
        error_detail: str | None = None,
    ) -> ThreeDVideoTaskView:
        row = await self._locked_task(video_task_id)
        if ThreeDVideoTaskStatus(row.status) in TERMINAL_THREE_D_VIDEO_STATUSES:
            return _task_view(row)
        row.status = status.value
        row.progress_percent = max(0, min(100, int(progress_percent)))
        row.stage = stage
        if error_detail is not None:
            row.error_detail = error_detail
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def update_status(
        self,
        *,
        video_task_id: UUID,
        status: ThreeDVideoTaskStatus,
        error_detail: str | None = None,
        execution_time_ms: int | None = None,
    ) -> ThreeDVideoTaskView:
        row = await self._locked_task(video_task_id)
        row.status = status.value
        if error_detail is not None:
            row.error_detail = error_detail
        if execution_time_ms is not None:
            row.execution_time_ms = execution_time_ms
        if status is ThreeDVideoTaskStatus.COMPLETED:
            row.progress_percent = 100
            row.stage = None
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def mark_failed(
        self, *, video_task_id: UUID, error_detail: str
    ) -> ThreeDVideoTaskView:
        row = await self._locked_task(video_task_id)
        if ThreeDVideoTaskStatus(row.status) is ThreeDVideoTaskStatus.FAILED:
            return _task_view(row)
        row.status = ThreeDVideoTaskStatus.FAILED.value
        row.error_detail = error_detail[:4000]
        row.stage = None
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def mark_completed(
        self, *, video_task_id: UUID, execution_time_ms: int | None = None
    ) -> ThreeDVideoTaskView:
        return await self.update_status(
            video_task_id=video_task_id,
            status=ThreeDVideoTaskStatus.COMPLETED,
            execution_time_ms=execution_time_ms,
        )

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
    ) -> VideoAssetView:
        stmt = select(VideoAsset).where(VideoAsset.video_task_id == video_task_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = VideoAsset(
                video_task_id=video_task_id,
                user_id=user_id,
            )
            self._session.add(row)

        if file_mp4_url is not None:
            row.file_mp4_url = file_mp4_url
        if file_webp_url is not None:
            row.file_webp_url = file_webp_url
        if file_gif_url is not None:
            row.file_gif_url = file_gif_url
        if file_size_bytes is not None:
            row.file_size_bytes = file_size_bytes
        if width is not None:
            row.width = width
        if height is not None:
            row.height = height

        await self._session.flush()
        return _asset_view(row)

    async def get_assets(self, *, video_task_id: UUID) -> VideoAssetView | None:
        stmt = select(VideoAsset).where(VideoAsset.video_task_id == video_task_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _asset_view(row) if row is not None else None

    async def get_assets_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> VideoAssetView | None:
        stmt = select(VideoAsset).where(
            VideoAsset.video_task_id == video_task_id,
            VideoAsset.user_id == user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _asset_view(row) if row is not None else None


__all__ = [
    "ThreeDVideoRepository",
    "parse_resolution",
]
