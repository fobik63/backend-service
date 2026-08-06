"""SQLAlchemy adapter for Zero-Knowledge source retention purge."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.generation import GenerationJobStatus
from app.domain.source_retention import SourceAssetCandidate, SourceRetentionStatus
from app.models.bulk_generation import BulkGenerationBatch, BulkGenerationItem
from app.models.generation_job import GenerationJob
from app.models.smart_variant import SmartVariantSync

_TERMINAL_JOB_STATUSES = (
    GenerationJobStatus.COMPLETED.value,
    GenerationJobStatus.FAILED.value,
)
_TERMINAL_BATCH_STATUSES = ("completed", "failed", "partial")
_AVAILABLE = SourceRetentionStatus.AVAILABLE.value
_DELETED = SourceRetentionStatus.DELETED.value


class SourceRetentionRepository:
    """Locate expired heavy assets and flip their retention status to deleted."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_purge_candidates(
        self,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[SourceAssetCandidate]:
        """Collect up to ``limit`` heavy assets older than ``cutoff``."""

        if limit <= 0:
            return []

        candidates: list[SourceAssetCandidate] = []
        remaining = limit

        job_anchor = func.coalesce(GenerationJob.completed_at, GenerationJob.created_at)
        job_rows = await self._session.execute(
            select(
                GenerationJob.id,
                GenerationJob.input_object_key,
                GenerationJob.input_retention_status,
                GenerationJob.archive_object_key,
                GenerationJob.archive_retention_status,
            )
            .where(
                GenerationJob.status.in_(_TERMINAL_JOB_STATUSES),
                job_anchor <= cutoff,
                or_(
                    GenerationJob.input_retention_status == _AVAILABLE,
                    and_(
                        GenerationJob.archive_object_key.is_not(None),
                        GenerationJob.archive_retention_status == _AVAILABLE,
                    ),
                ),
            )
            .order_by(job_anchor.asc())
            .limit(remaining)
        )
        for (
            job_id,
            input_key,
            input_status,
            archive_key,
            archive_status,
        ) in job_rows.all():
            if input_status == _AVAILABLE and input_key and input_key.strip():
                candidates.append(
                    SourceAssetCandidate(
                        kind="generation_input",
                        record_id=job_id,
                        object_key=input_key.strip(),
                        field_name="input_object_key",
                    )
                )
            if (
                archive_status == _AVAILABLE
                and archive_key
                and archive_key.strip()
            ):
                candidates.append(
                    SourceAssetCandidate(
                        kind="generation_archive",
                        record_id=job_id,
                        object_key=archive_key.strip(),
                        field_name="archive_object_key",
                    )
                )

        remaining = limit - len(candidates)
        if remaining <= 0:
            return candidates[:limit]

        batch_anchor = func.coalesce(
            BulkGenerationBatch.completed_at, BulkGenerationBatch.created_at
        )
        bulk_rows = await self._session.execute(
            select(
                BulkGenerationBatch.id,
                BulkGenerationBatch.source_zip_object_key,
            )
            .where(
                BulkGenerationBatch.status.in_(_TERMINAL_BATCH_STATUSES),
                BulkGenerationBatch.source_zip_retention_status == _AVAILABLE,
                batch_anchor <= cutoff,
            )
            .order_by(batch_anchor.asc())
            .limit(remaining)
        )
        for batch_id, zip_key in bulk_rows.all():
            if zip_key and zip_key.strip():
                candidates.append(
                    SourceAssetCandidate(
                        kind="bulk_zip",
                        record_id=batch_id,
                        object_key=zip_key.strip(),
                        field_name="source_zip_object_key",
                    )
                )

        remaining = limit - len(candidates)
        if remaining <= 0:
            return candidates[:limit]

        item_rows = await self._session.execute(
            select(BulkGenerationItem.id, BulkGenerationItem.input_object_key)
            .join(
                BulkGenerationBatch,
                BulkGenerationItem.batch_id == BulkGenerationBatch.id,
            )
            .where(
                BulkGenerationBatch.status.in_(_TERMINAL_BATCH_STATUSES),
                BulkGenerationItem.input_retention_status == _AVAILABLE,
                BulkGenerationItem.input_object_key.is_not(None),
                batch_anchor <= cutoff,
            )
            .order_by(batch_anchor.asc())
            .limit(remaining)
        )
        for item_id, input_key in item_rows.all():
            if input_key and input_key.strip():
                candidates.append(
                    SourceAssetCandidate(
                        kind="bulk_item_input",
                        record_id=item_id,
                        object_key=input_key.strip(),
                        field_name="input_object_key",
                    )
                )

        remaining = limit - len(candidates)
        if remaining <= 0:
            return candidates[:limit]

        sync_anchor = func.coalesce(
            SmartVariantSync.completed_at, SmartVariantSync.created_at
        )
        sync_rows = await self._session.execute(
            select(
                SmartVariantSync.id,
                SmartVariantSync.source_image_object_key,
            )
            .where(
                SmartVariantSync.status.in_(_TERMINAL_BATCH_STATUSES),
                SmartVariantSync.source_retention_status == _AVAILABLE,
                sync_anchor <= cutoff,
            )
            .order_by(sync_anchor.asc())
            .limit(remaining)
        )
        for sync_id, source_key in sync_rows.all():
            if source_key and source_key.strip():
                candidates.append(
                    SourceAssetCandidate(
                        kind="smart_variant_source",
                        record_id=sync_id,
                        object_key=source_key.strip(),
                        field_name="source_image_object_key",
                    )
                )

        return candidates[:limit]

    async def mark_generation_input_deleted(self, *, job_id: UUID) -> bool:
        result = await self._session.execute(
            update(GenerationJob)
            .where(
                GenerationJob.id == job_id,
                GenerationJob.input_retention_status == _AVAILABLE,
            )
            .values(input_retention_status=_DELETED)
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_generation_archive_deleted(self, *, job_id: UUID) -> bool:
        result = await self._session.execute(
            update(GenerationJob)
            .where(
                GenerationJob.id == job_id,
                GenerationJob.archive_retention_status == _AVAILABLE,
            )
            .values(
                archive_retention_status=_DELETED,
                archive_object_key=None,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_bulk_zip_deleted(self, *, batch_id: UUID) -> bool:
        result = await self._session.execute(
            update(BulkGenerationBatch)
            .where(
                BulkGenerationBatch.id == batch_id,
                BulkGenerationBatch.source_zip_retention_status == _AVAILABLE,
            )
            .values(source_zip_retention_status=_DELETED)
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_bulk_item_input_deleted(self, *, item_id: UUID) -> bool:
        result = await self._session.execute(
            update(BulkGenerationItem)
            .where(
                BulkGenerationItem.id == item_id,
                BulkGenerationItem.input_retention_status == _AVAILABLE,
            )
            .values(
                input_retention_status=_DELETED,
                input_object_key=None,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_smart_variant_source_deleted(self, *, sync_id: UUID) -> bool:
        result = await self._session.execute(
            update(SmartVariantSync)
            .where(
                SmartVariantSync.id == sync_id,
                SmartVariantSync.source_retention_status == _AVAILABLE,
            )
            .values(source_retention_status=_DELETED)
        )
        await self._session.commit()
        return bool(result.rowcount)
