"""SQLAlchemy adapter for Bulk Generation persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.bulk_generation import (
    BulkBatchStatus,
    BulkBatchView,
    BulkItemStatus,
    BulkItemView,
    map_job_status_to_item,
    resolve_batch_terminal_status,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)
from app.models.bulk_generation import BulkGenerationBatch, BulkGenerationItem
from app.models.generation_job import GenerationJob
from app.models.user import User


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _item_view(row: BulkGenerationItem) -> BulkItemView:
    return BulkItemView(
        id=row.id,
        batch_id=row.batch_id,
        position=row.position,
        product_key=row.product_key,
        source_path=row.source_path,
        status=BulkItemStatus(row.status),
        input_object_key=row.input_object_key,
        generation_job_id=row.generation_job_id,
        error_message=row.error_message,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
    )


def _batch_view(
    row: BulkGenerationBatch, *, include_items: bool
) -> BulkBatchView:
    items: tuple[BulkItemView, ...] = ()
    if include_items and row.items is not None:
        items = tuple(_item_view(item) for item in row.items)
    return BulkBatchView(
        id=row.id,
        user_id=row.user_id,
        status=BulkBatchStatus(row.status),
        product_category=row.product_category,
        engine_mode=row.engine_mode,
        post_processing_mode=row.post_processing_mode,
        apply_text_overlays=row.apply_text_overlays,
        source_zip_object_key=row.source_zip_object_key,
        total_items=row.total_items,
        completed_items=row.completed_items,
        failed_items=row.failed_items,
        skipped_items=row.skipped_items,
        notify_telegram=row.notify_telegram,
        notify_push=row.notify_push,
        telegram_notified_at=(
            _to_utc(row.telegram_notified_at)
            if row.telegram_notified_at is not None
            else None
        ),
        push_notified_at=(
            _to_utc(row.push_notified_at) if row.push_notified_at is not None else None
        ),
        error_message=row.error_message,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=(
            _to_utc(row.completed_at) if row.completed_at is not None else None
        ),
        items=items,
    )


class BulkGenerationRepository:
    """Persist bulk batches, items, and completion counters."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_idempotent_batch(
        self, *, user_id: UUID, idempotency_key: str
    ) -> BulkBatchView | None:
        row = await self._session.scalar(
            select(BulkGenerationBatch)
            .where(
                BulkGenerationBatch.user_id == user_id,
                BulkGenerationBatch.idempotency_key == idempotency_key,
            )
            .options(selectinload(BulkGenerationBatch.items))
        )
        if row is None:
            return None
        return _batch_view(row, include_items=True)

    async def create_batch(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_zip_object_key: str,
        notify_telegram: bool,
        notify_push: bool,
    ) -> BulkBatchView:
        now = datetime.now(UTC)
        row = BulkGenerationBatch(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=BulkBatchStatus.QUEUED.value,
            product_category=product_category,
            engine_mode=engine_mode.value,
            post_processing_mode=post_processing_mode.value,
            apply_text_overlays=apply_text_overlays,
            source_zip_object_key=source_zip_object_key,
            notify_telegram=notify_telegram,
            notify_push=notify_push,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _batch_view(row, include_items=True)

    async def get_batch_for_user(
        self, *, user_id: UUID, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        stmt = select(BulkGenerationBatch).where(
            BulkGenerationBatch.id == batch_id,
            BulkGenerationBatch.user_id == user_id,
        )
        if include_items:
            stmt = stmt.options(selectinload(BulkGenerationBatch.items))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _batch_view(row, include_items=include_items)

    async def get_batch(
        self, *, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        stmt = select(BulkGenerationBatch).where(BulkGenerationBatch.id == batch_id)
        if include_items:
            stmt = stmt.options(selectinload(BulkGenerationBatch.items))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _batch_view(row, include_items=include_items)

    async def mark_batch_status(
        self,
        *,
        batch_id: UUID,
        status: BulkBatchStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> BulkBatchView:
        row = await self._session.scalar(
            select(BulkGenerationBatch)
            .where(BulkGenerationBatch.id == batch_id)
            .options(selectinload(BulkGenerationBatch.items))
        )
        if row is None:
            raise LookupError(f"Bulk batch {batch_id} not found.")
        row.status = status.value
        row.updated_at = datetime.now(UTC)
        if error_message is not None:
            row.error_message = error_message
        if total_items is not None:
            row.total_items = total_items
        if completed_at is not None:
            row.completed_at = completed_at
        await self._session.commit()
        await self._session.refresh(row)
        return _batch_view(row, include_items=True)

    async def replace_pending_items(
        self,
        *,
        batch_id: UUID,
        items: tuple[tuple[int, str, str], ...],
    ) -> tuple[BulkItemView, ...]:
        await self._session.execute(
            delete(BulkGenerationItem).where(BulkGenerationItem.batch_id == batch_id)
        )
        now = datetime.now(UTC)
        created: list[BulkGenerationItem] = []
        for position, product_key, source_path in items:
            item = BulkGenerationItem(
                batch_id=batch_id,
                position=position,
                product_key=product_key,
                source_path=source_path,
                status=BulkItemStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            self._session.add(item)
            created.append(item)
        batch = await self._session.get(BulkGenerationBatch, batch_id)
        if batch is not None:
            batch.total_items = len(items)
            batch.completed_items = 0
            batch.failed_items = 0
            batch.skipped_items = 0
            batch.updated_at = now
        await self._session.commit()
        for item in created:
            await self._session.refresh(item)
        return tuple(_item_view(item) for item in created)

    async def mark_item_input(
        self,
        *,
        item_id: UUID,
        input_object_key: str,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        item = await self._session.get(BulkGenerationItem, item_id)
        if item is None:
            raise LookupError(f"Bulk item {item_id} not found.")
        item.input_object_key = input_object_key
        item.status = status.value
        item.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return _item_view(item)

    async def mark_item_job(
        self,
        *,
        item_id: UUID,
        generation_job_id: UUID,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        item = await self._session.get(BulkGenerationItem, item_id)
        if item is None:
            raise LookupError(f"Bulk item {item_id} not found.")
        item.generation_job_id = generation_job_id
        item.status = status.value
        item.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return _item_view(item)

    async def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_message: str,
        status: BulkItemStatus = BulkItemStatus.FAILED,
    ) -> BulkItemView:
        item = await self._session.get(BulkGenerationItem, item_id)
        if item is None:
            raise LookupError(f"Bulk item {item_id} not found.")
        item.status = status.value
        item.error_message = error_message
        item.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return _item_view(item)

    async def list_active_batch_ids(self, *, limit: int) -> tuple[UUID, ...]:
        rows = await self._session.scalars(
            select(BulkGenerationBatch.id)
            .where(
                BulkGenerationBatch.status.in_(
                    (
                        BulkBatchStatus.QUEUED.value,
                        BulkBatchStatus.UNPACKING.value,
                        BulkBatchStatus.RUNNING.value,
                    )
                )
            )
            .order_by(BulkGenerationBatch.created_at.asc())
            .limit(limit)
        )
        return tuple(rows.all())

    async def sync_item_statuses_from_jobs(self, *, batch_id: UUID) -> BulkBatchView:
        row = await self._session.scalar(
            select(BulkGenerationBatch)
            .where(BulkGenerationBatch.id == batch_id)
            .options(selectinload(BulkGenerationBatch.items))
        )
        if row is None:
            raise LookupError(f"Bulk batch {batch_id} not found.")

        now = datetime.now(UTC)
        completed = 0
        failed = 0
        skipped = 0
        for item in row.items:
            if item.status == BulkItemStatus.SKIPPED.value:
                skipped += 1
                continue
            if item.generation_job_id is None:
                if item.status == BulkItemStatus.FAILED.value:
                    failed += 1
                continue
            job = await self._session.get(GenerationJob, item.generation_job_id)
            if job is None:
                item.status = BulkItemStatus.FAILED.value
                item.error_message = item.error_message or "Linked generation job missing."
                item.updated_at = now
                failed += 1
                continue
            mapped = map_job_status_to_item(job.status)
            if item.status != mapped.value:
                item.status = mapped.value
                item.updated_at = now
            if mapped is BulkItemStatus.COMPLETED:
                completed += 1
            elif mapped is BulkItemStatus.FAILED:
                failed += 1

        row.completed_items = completed
        row.failed_items = failed
        row.skipped_items = skipped
        row.updated_at = now

        terminal = resolve_batch_terminal_status(
            total_items=row.total_items,
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
        )
        if terminal is not None and row.status not in (
            BulkBatchStatus.COMPLETED.value,
            BulkBatchStatus.PARTIAL.value,
            BulkBatchStatus.FAILED.value,
        ):
            row.status = terminal.value
            row.completed_at = now

        await self._session.commit()
        await self._session.refresh(row)
        return _batch_view(row, include_items=True)

    async def mark_notified(
        self,
        *,
        batch_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> BulkBatchView:
        row = await self._session.scalar(
            select(BulkGenerationBatch)
            .where(BulkGenerationBatch.id == batch_id)
            .options(selectinload(BulkGenerationBatch.items))
        )
        if row is None:
            raise LookupError(f"Bulk batch {batch_id} not found.")
        if telegram_at is not None:
            row.telegram_notified_at = telegram_at
        if push_at is not None:
            row.push_notified_at = push_at
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _batch_view(row, include_items=True)

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        return user.telegram_id

    async def get_job_status(self, job_id: UUID) -> GenerationJobStatus | None:
        job = await self._session.get(GenerationJob, job_id)
        if job is None:
            return None
        return GenerationJobStatus(job.status)
