"""SQLAlchemy adapter for Smart Variant Sync persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)
from app.domain.smart_variant import (
    ColorSpec,
    VariantItemStatus,
    VariantItemView,
    VariantSyncStatus,
    VariantSyncView,
    map_job_status_to_item,
    resolve_sync_terminal_status,
)
from app.infrastructure.persistence.batching import (
    DEFAULT_UPSERT_BATCH_SIZE,
    chunk_rows,
)
from app.models.generation_job import GenerationJob
from app.models.smart_variant import SmartVariantItem, SmartVariantSync
from app.models.user import User


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _item_view(row: SmartVariantItem) -> VariantItemView:
    return VariantItemView(
        id=row.id,
        sync_id=row.sync_id,
        position=row.position,
        color_name=row.color_name,
        color_hex=row.color_hex,
        color_slug=row.color_slug,
        status=VariantItemStatus(row.status),
        recolored_object_key=row.recolored_object_key,
        generation_job_id=row.generation_job_id,
        error_message=row.error_message,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
    )


def _sync_view(row: SmartVariantSync, *, include_items: bool) -> VariantSyncView:
    items: tuple[VariantItemView, ...] = ()
    if include_items and row.items is not None:
        items = tuple(_item_view(item) for item in row.items)
    return VariantSyncView(
        id=row.id,
        user_id=row.user_id,
        status=VariantSyncStatus(row.status),
        product_category=row.product_category,
        engine_mode=row.engine_mode,
        post_processing_mode=row.post_processing_mode,
        apply_text_overlays=row.apply_text_overlays,
        source_image_object_key=row.source_image_object_key,
        source_mime_type=row.source_mime_type,
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


class SmartVariantRepository:
    """Persist smart variant syncs, color items, and completion counters."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_idempotent_sync(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VariantSyncView | None:
        row = await self._session.scalar(
            select(SmartVariantSync)
            .where(
                SmartVariantSync.user_id == user_id,
                SmartVariantSync.idempotency_key == idempotency_key,
            )
            .options(selectinload(SmartVariantSync.items))
        )
        if row is None:
            return None
        return _sync_view(row, include_items=True)

    async def create_sync(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_image_object_key: str,
        source_mime_type: str,
        colors: tuple[ColorSpec, ...],
        notify_telegram: bool,
        notify_push: bool,
    ) -> VariantSyncView:
        now = datetime.now(UTC)
        row = SmartVariantSync(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=VariantSyncStatus.QUEUED.value,
            product_category=product_category,
            engine_mode=engine_mode.value,
            post_processing_mode=post_processing_mode.value,
            apply_text_overlays=apply_text_overlays,
            source_image_object_key=source_image_object_key,
            source_mime_type=source_mime_type,
            total_items=len(colors),
            notify_telegram=notify_telegram,
            notify_push=notify_push,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        payloads: list[dict] = [
            {
                "id": uuid4(),
                "sync_id": row.id,
                "position": position,
                "color_name": color.name,
                "color_hex": color.normalize_hex(),
                "color_slug": color.slug,
                "status": VariantItemStatus.PENDING.value,
                "created_at": now,
                "updated_at": now,
            }
            for position, color in enumerate(colors, start=1)
        ]
        for batch_rows in chunk_rows(payloads, DEFAULT_UPSERT_BATCH_SIZE):
            insert_stmt = pg_insert(SmartVariantItem).values(batch_rows)
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["sync_id", "position"],
                set_={
                    "color_name": insert_stmt.excluded.color_name,
                    "color_hex": insert_stmt.excluded.color_hex,
                    "color_slug": insert_stmt.excluded.color_slug,
                    "status": insert_stmt.excluded.status,
                    "updated_at": insert_stmt.excluded.updated_at,
                },
            )
            await self._session.execute(stmt)
        await self._session.commit()
        refreshed = await self._session.scalar(
            select(SmartVariantSync)
            .where(SmartVariantSync.id == row.id)
            .options(selectinload(SmartVariantSync.items))
        )
        assert refreshed is not None
        return _sync_view(refreshed, include_items=True)

    async def get_sync_for_user(
        self, *, user_id: UUID, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        stmt = select(SmartVariantSync).where(
            SmartVariantSync.id == sync_id,
            SmartVariantSync.user_id == user_id,
        )
        if include_items:
            stmt = stmt.options(selectinload(SmartVariantSync.items))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _sync_view(row, include_items=include_items)

    async def get_sync(
        self, *, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        stmt = select(SmartVariantSync).where(SmartVariantSync.id == sync_id)
        if include_items:
            stmt = stmt.options(selectinload(SmartVariantSync.items))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _sync_view(row, include_items=include_items)

    async def mark_sync_status(
        self,
        *,
        sync_id: UUID,
        status: VariantSyncStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> VariantSyncView:
        row = await self._session.scalar(
            select(SmartVariantSync)
            .where(SmartVariantSync.id == sync_id)
            .options(selectinload(SmartVariantSync.items))
        )
        if row is None:
            raise LookupError(f"Smart variant sync {sync_id} not found.")
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
        return _sync_view(row, include_items=True)

    async def mark_item_recoloring(self, *, item_id: UUID) -> VariantItemView:
        item = await self._session.get(SmartVariantItem, item_id)
        if item is None:
            raise LookupError(f"Smart variant item {item_id} not found.")
        item.status = VariantItemStatus.RECOLORING.value
        item.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return _item_view(item)

    async def mark_item_recolored(
        self,
        *,
        item_id: UUID,
        recolored_object_key: str,
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        item = await self._session.get(SmartVariantItem, item_id)
        if item is None:
            raise LookupError(f"Smart variant item {item_id} not found.")
        item.recolored_object_key = recolored_object_key
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
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        item = await self._session.get(SmartVariantItem, item_id)
        if item is None:
            raise LookupError(f"Smart variant item {item_id} not found.")
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
        status: VariantItemStatus = VariantItemStatus.FAILED,
    ) -> VariantItemView:
        item = await self._session.get(SmartVariantItem, item_id)
        if item is None:
            raise LookupError(f"Smart variant item {item_id} not found.")
        item.status = status.value
        item.error_message = error_message
        item.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return _item_view(item)

    async def list_active_sync_ids(self, *, limit: int) -> tuple[UUID, ...]:
        rows = await self._session.scalars(
            select(SmartVariantSync.id)
            .where(
                SmartVariantSync.status.in_(
                    (
                        VariantSyncStatus.QUEUED.value,
                        VariantSyncStatus.RECOLORING.value,
                        VariantSyncStatus.RUNNING.value,
                    )
                )
            )
            .order_by(SmartVariantSync.created_at.asc())
            .limit(limit)
        )
        return tuple(rows.all())

    async def sync_item_statuses_from_jobs(self, *, sync_id: UUID) -> VariantSyncView:
        row = await self._session.scalar(
            select(SmartVariantSync)
            .where(SmartVariantSync.id == sync_id)
            .options(selectinload(SmartVariantSync.items))
        )
        if row is None:
            raise LookupError(f"Smart variant sync {sync_id} not found.")

        now = datetime.now(UTC)
        completed = 0
        failed = 0
        skipped = 0
        for item in row.items:
            if item.status == VariantItemStatus.SKIPPED.value:
                skipped += 1
                continue
            if item.generation_job_id is None:
                if item.status == VariantItemStatus.FAILED.value:
                    failed += 1
                continue
            job = await self._session.get(GenerationJob, item.generation_job_id)
            if job is None:
                item.status = VariantItemStatus.FAILED.value
                item.error_message = item.error_message or "Linked generation job missing."
                item.updated_at = now
                failed += 1
                continue
            mapped = map_job_status_to_item(job.status)
            if item.status != mapped.value:
                item.status = mapped.value
                item.updated_at = now
            if mapped is VariantItemStatus.COMPLETED:
                completed += 1
            elif mapped is VariantItemStatus.FAILED:
                failed += 1

        row.completed_items = completed
        row.failed_items = failed
        row.skipped_items = skipped
        row.updated_at = now

        terminal = resolve_sync_terminal_status(
            total_items=row.total_items,
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
        )
        if terminal is not None and row.status not in (
            VariantSyncStatus.COMPLETED.value,
            VariantSyncStatus.PARTIAL.value,
            VariantSyncStatus.FAILED.value,
        ):
            row.status = terminal.value
            row.completed_at = now

        await self._session.commit()
        await self._session.refresh(row)
        return _sync_view(row, include_items=True)

    async def mark_notified(
        self,
        *,
        sync_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> VariantSyncView:
        row = await self._session.scalar(
            select(SmartVariantSync)
            .where(SmartVariantSync.id == sync_id)
            .options(selectinload(SmartVariantSync.items))
        )
        if row is None:
            raise LookupError(f"Smart variant sync {sync_id} not found.")
        if telegram_at is not None:
            row.telegram_notified_at = telegram_at
        if push_at is not None:
            row.push_notified_at = push_at
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _sync_view(row, include_items=True)

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
