"""SQLAlchemy persistence for 3D generation tasks, assets, and GPU rentals."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.three_d import (
    TERMINAL_THREE_D_STATUSES,
    GpuRentalSessionStatus,
    GpuRentalSessionView,
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDOutputFormat,
    ThreeDTaskStatus,
    ThreeDTaskView,
)
from app.models.three_d import GpuRentalSession, ThreeDAsset, ThreeDTask
from app.core.pricing import BillingService as OperationBillingService
from app.core.pricing import CoinHoldStatus, PricingNotFoundError
from app.services.billing_service import (
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)


def _parse_output_format(raw: str | None) -> ThreeDOutputFormat | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return ThreeDOutputFormat(str(raw).strip().upper())
    except ValueError:
        return None


def _task_view(row: ThreeDTask) -> ThreeDTaskView:
    return ThreeDTaskView(
        id=row.id,
        user_id=row.user_id,
        status=ThreeDTaskStatus(row.status),
        input_type=ThreeDInputType(row.input_type),
        prompt=row.prompt,
        source_image_url=row.source_image_url,
        provider_name=row.provider_name,
        provider_job_id=row.provider_job_id,
        cost_coins=int(row.cost_coins),
        progress_percent=int(row.progress_percent or 0),
        stage=row.stage,
        celery_task_id=row.celery_task_id,
        coins_held=bool(row.coins_held),
        coins_captured=bool(row.coins_captured),
        coins_refunded=bool(row.coins_refunded),
        polycount_target=row.polycount_target,
        texture_resolution=row.texture_resolution,
        output_format=_parse_output_format(row.output_format),
        idempotency_key=row.idempotency_key,
        error_message=row.error_message,
        execution_time_seconds=row.execution_time_seconds,
        created_at=row.created_at,
        updated_at=row.updated_at,
        coin_hold_id=row.coin_hold_id,
    )


def _asset_view(row: ThreeDAsset) -> ThreeDAssetView:
    return ThreeDAssetView(
        id=row.id,
        task_id=row.task_id,
        user_id=row.user_id,
        file_glb_url=row.file_glb_url,
        file_usdz_url=row.file_usdz_url,
        file_obj_url=row.file_obj_url,
        preview_png_url=row.preview_png_url,
        thumbnail_url=row.thumbnail_url,
        polycount_actual=row.polycount_actual,
        file_size_bytes=row.file_size_bytes,
    )


def _gpu_view(row: GpuRentalSession) -> GpuRentalSessionView:
    return GpuRentalSessionView(
        id=row.id,
        user_id=row.user_id,
        provider_name=row.provider_name,
        instance_type=row.instance_type,
        status=GpuRentalSessionStatus(row.status),
        hourly_rate_coins=int(row.hourly_rate_coins),
        started_at=row.started_at,
        stopped_at=row.stopped_at,
        total_cost_coins=int(row.total_cost_coins),
    )


def billed_minutes(started_at: datetime | None, stopped_at: datetime | None) -> int:
    """Whole minutes charged for a GPU rental window (minimum 1 when started)."""

    if started_at is None:
        return 0
    end = stopped_at or datetime.now(UTC)
    start = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    end = end if end.tzinfo else end.replace(tzinfo=UTC)
    seconds = max(0.0, (end - start).total_seconds())
    return max(1, int(math.ceil(seconds / 60.0)))


class ThreeDRepository:
    """Unit-of-work repository for ``three_d_tasks`` / ``three_d_assets``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
    ) -> ThreeDTaskView:
        row = ThreeDTask(
            user_id=user_id,
            status=ThreeDTaskStatus.PENDING.value,
            input_type=input_type.value,
            prompt=prompt,
            source_image_url=source_image_url,
            provider_name=provider_name,
            cost_coins=max(0, int(cost_coins)),
            progress_percent=0,
            polycount_target=polycount_target,
            texture_resolution=texture_resolution,
            output_format=output_format.value if output_format is not None else None,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDTaskView | None:
        row = await self._session.scalar(
            select(ThreeDTask)
            .where(
                ThreeDTask.user_id == user_id,
                ThreeDTask.idempotency_key == idempotency_key,
            )
            .limit(1)
        )
        return _task_view(row) if row is not None else None

    async def get_task(self, task_id: UUID) -> ThreeDTaskView | None:
        row = await self._session.get(ThreeDTask, task_id)
        return _task_view(row) if row is not None else None

    async def get_task_for_user(
        self, *, task_id: UUID, user_id: UUID
    ) -> ThreeDTaskView | None:
        row = await self._session.scalar(
            select(ThreeDTask)
            .where(ThreeDTask.id == task_id, ThreeDTask.user_id == user_id)
            .limit(1)
        )
        return _task_view(row) if row is not None else None

    async def attach_celery_task(
        self, *, task_id: UUID, celery_task_id: str
    ) -> ThreeDTaskView:
        row = await self._locked_task(task_id)
        row.celery_task_id = celery_task_id[:255]
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def hold_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        """Freeze ``cost_coins`` via ``app.core.pricing.BillingService`` hold ledger."""

        row = await self._locked_task(task_id)
        if row.coins_held or row.coins_captured:
            return _task_view(row)
        amount = int(row.cost_coins)
        billing = OperationBillingService(self._session)
        try:
            hold_id = await billing.hold_coins(
                row.user_id,
                amount,
                service_type="three_d",
                reference_id=row.id,
                idempotency_key=row.idempotency_key,
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

    async def capture_held_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        """Convert a hold into a final charge (balance already debited)."""

        row = await self._locked_task(task_id)
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
                # Legacy rows without a ledger entry still settle on task flags.
                pass
        row.coins_held = False
        row.coins_captured = True
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def release_held_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        """Unfreeze held coins by refunding the debit."""

        row = await self._locked_task(task_id)
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
                    # Already settled elsewhere; keep task flags consistent.
                    pass
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

    async def mark_provider_submitted(
        self,
        *,
        task_id: UUID,
        provider_job_id: str,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
    ) -> ThreeDTaskView:
        row = await self._locked_task(task_id)
        row.provider_job_id = provider_job_id[:255]
        row.status = status.value
        row.progress_percent = max(0, min(100, int(progress_percent)))
        row.stage = stage
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def update_progress(
        self,
        *,
        task_id: UUID,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
        error_message: str | None = None,
        provider_job_id: str | None = None,
    ) -> ThreeDTaskView:
        row = await self._locked_task(task_id)
        if ThreeDTaskStatus(row.status) in TERMINAL_THREE_D_STATUSES:
            return _task_view(row)
        row.status = status.value
        row.progress_percent = max(0, min(100, int(progress_percent)))
        row.stage = stage
        if error_message is not None:
            row.error_message = error_message[:4000]
        if provider_job_id is not None and provider_job_id.strip():
            row.provider_job_id = provider_job_id.strip()[:255]
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

    async def mark_failed(
        self,
        *,
        task_id: UUID,
        error_message: str,
        release_coins: bool = True,
    ) -> ThreeDTaskView:
        row = await self._locked_task(task_id)
        if ThreeDTaskStatus(row.status) == ThreeDTaskStatus.FAILED and row.coins_refunded:
            return _task_view(row)
        row.status = ThreeDTaskStatus.FAILED.value
        row.error_message = (error_message or "3D generation failed.")[:4000]
        row.progress_percent = min(int(row.progress_percent or 0), 100)
        row.stage = None
        row.updated_at = datetime.now(UTC)
        if release_coins and row.coins_held and not row.coins_captured and not row.coins_refunded:
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
        await self._session.commit()
        await self._session.refresh(row)
        return _task_view(row)

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
    ) -> tuple[ThreeDTaskView, ThreeDAssetView]:
        row = await self._locked_task(task_id)
        if ThreeDTaskStatus(row.status) == ThreeDTaskStatus.COMPLETED:
            existing = await self.get_asset_for_task(task_id)
            if existing is not None:
                return _task_view(row), existing

        row.status = ThreeDTaskStatus.COMPLETED.value
        row.progress_percent = 100
        row.stage = None
        row.error_message = None
        row.execution_time_seconds = execution_time_seconds
        row.updated_at = datetime.now(UTC)
        if row.coins_held and not row.coins_captured:
            row.coins_held = False
            row.coins_captured = True

        asset = await self._session.scalar(
            select(ThreeDAsset).where(ThreeDAsset.task_id == task_id).limit(1)
        )
        if asset is None:
            asset = ThreeDAsset(task_id=row.id, user_id=row.user_id)
            self._session.add(asset)
        asset.file_glb_url = file_glb_url
        asset.file_usdz_url = file_usdz_url
        asset.file_obj_url = file_obj_url
        asset.preview_png_url = preview_png_url
        asset.thumbnail_url = thumbnail_url
        asset.polycount_actual = polycount_actual
        asset.file_size_bytes = file_size_bytes
        await self._session.commit()
        await self._session.refresh(row)
        await self._session.refresh(asset)
        return _task_view(row), _asset_view(asset)

    async def get_asset_for_task(self, task_id: UUID) -> ThreeDAssetView | None:
        row = await self._session.scalar(
            select(ThreeDAsset).where(ThreeDAsset.task_id == task_id).limit(1)
        )
        return _asset_view(row) if row is not None else None

    async def list_assets_for_user(
        self, *, user_id: UUID, limit: int, offset: int
    ) -> tuple[tuple[ThreeDAssetView, ...], int]:
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(ThreeDAsset)
                .where(ThreeDAsset.user_id == user_id)
            )
            or 0
        )
        rows = (
            await self._session.scalars(
                select(ThreeDAsset)
                .where(ThreeDAsset.user_id == user_id)
                .order_by(ThreeDAsset.id.desc())
                .offset(safe_offset)
                .limit(safe_limit)
            )
        ).all()
        return tuple(_asset_view(row) for row in rows), total

    async def list_active_task_ids(self, *, limit: int) -> tuple[UUID, ...]:
        rows = (
            await self._session.scalars(
                select(ThreeDTask.id)
                .where(
                    ThreeDTask.status.in_(
                        (
                            ThreeDTaskStatus.PENDING.value,
                            ThreeDTaskStatus.PROCESSING.value,
                        )
                    ),
                    ThreeDTask.provider_job_id.is_not(None),
                )
                .order_by(ThreeDTask.updated_at.asc())
                .limit(max(1, min(limit, 200)))
            )
        ).all()
        return tuple(rows)

    async def get_by_provider_job_id(
        self, *, provider_name: str, provider_job_id: str
    ) -> ThreeDTaskView | None:
        row = await self._session.scalar(
            select(ThreeDTask)
            .where(
                ThreeDTask.provider_name == provider_name,
                ThreeDTask.provider_job_id == provider_job_id,
            )
            .limit(1)
        )
        return _task_view(row) if row is not None else None

    async def get_active_gpu_rental(
        self, *, user_id: UUID
    ) -> GpuRentalSessionView | None:
        row = await self._session.scalar(
            select(GpuRentalSession)
            .where(
                GpuRentalSession.user_id == user_id,
                GpuRentalSession.status.in_(
                    (
                        GpuRentalSessionStatus.STARTING.value,
                        GpuRentalSessionStatus.RUNNING.value,
                    )
                ),
            )
            .order_by(GpuRentalSession.started_at.desc().nullslast())
            .limit(1)
        )
        return _gpu_view(row) if row is not None else None

    async def create_gpu_rental(
        self,
        *,
        user_id: UUID,
        provider_name: str,
        instance_type: str,
        hourly_rate_coins: int,
    ) -> GpuRentalSessionView:
        now = datetime.now(UTC)
        row = GpuRentalSession(
            user_id=user_id,
            provider_name=provider_name[:64],
            instance_type=instance_type[:128],
            status=GpuRentalSessionStatus.RUNNING.value,
            hourly_rate_coins=max(0, int(hourly_rate_coins)),
            started_at=now,
            stopped_at=None,
            total_cost_coins=0,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _gpu_view(row)

    async def get_gpu_rental_for_user(
        self, *, session_id: UUID, user_id: UUID
    ) -> GpuRentalSessionView | None:
        row = await self._session.scalar(
            select(GpuRentalSession)
            .where(
                GpuRentalSession.id == session_id,
                GpuRentalSession.user_id == user_id,
            )
            .limit(1)
        )
        return _gpu_view(row) if row is not None else None

    async def stop_gpu_rental(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        total_cost_coins: int,
        debit_coins: bool = True,
        status: GpuRentalSessionStatus = GpuRentalSessionStatus.STOPPED,
    ) -> GpuRentalSessionView:
        row = await self._session.scalar(
            select(GpuRentalSession)
            .where(
                GpuRentalSession.id == session_id,
                GpuRentalSession.user_id == user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise LookupError(f"GPU rental session {session_id} was not found.")
        if row.status in {
            GpuRentalSessionStatus.STOPPED.value,
            GpuRentalSessionStatus.TERMINATED.value,
        }:
            return _gpu_view(row)
        amount = max(0, int(total_cost_coins))
        if debit_coins and amount > 0:
            try:
                await BillingService(self._session).debit_coins_in_transaction(
                    user_id=user_id,
                    amount=amount,
                )
            except BillingNotFoundError as exc:
                raise LookupError("User was not found.") from exc
            except BillingValidationError:
                raise
        row.status = status.value
        row.stopped_at = datetime.now(UTC)
        row.total_cost_coins = amount
        await self._session.commit()
        await self._session.refresh(row)
        return _gpu_view(row)

    async def _locked_task(self, task_id: UUID) -> ThreeDTask:
        row = await self._session.scalar(
            select(ThreeDTask).where(ThreeDTask.id == task_id).with_for_update()
        )
        if row is None:
            raise LookupError(f"3D task {task_id} was not found.")
        return row
