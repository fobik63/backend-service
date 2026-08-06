"""Zero-Knowledge use case: purge heavy originals/ZIPs after the retention window."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.application.ports.source_retention import (
    SourceRetentionObjectStoragePort,
    SourceRetentionPersistencePort,
)
from app.domain.source_retention import (
    SourceAssetCandidate,
    SourceRetentionPurgeResult,
)

logger = logging.getLogger(__name__)


class SourceRetentionService:
    """Delete heavy S3 sources after N hours; keep lightweight thumbnails."""

    def __init__(
        self,
        repository: SourceRetentionPersistencePort,
        storage: SourceRetentionObjectStoragePort,
        *,
        retention_hours: int = 24,
        batch_limit: int = 200,
    ) -> None:
        if retention_hours <= 0:
            raise ValueError("retention_hours must be positive.")
        if batch_limit <= 0:
            raise ValueError("batch_limit must be positive.")
        self._repository = repository
        self._storage = storage
        self._retention_hours = retention_hours
        self._batch_limit = batch_limit

    async def purge_expired_sources(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> SourceRetentionPurgeResult:
        """Irreversibly delete expired ZIP archives and original photos from S3."""

        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        else:
            moment = moment.astimezone(UTC)
        cutoff = moment - timedelta(hours=self._retention_hours)
        batch_limit = limit if limit is not None else self._batch_limit

        candidates = await self._repository.list_purge_candidates(
            cutoff=cutoff,
            limit=batch_limit,
        )
        deleted = 0
        failed = 0
        marked = 0
        failed_keys: list[str] = []

        for candidate in candidates:
            try:
                await self._storage.delete_object(object_key=candidate.object_key)
            except Exception:
                failed += 1
                failed_keys.append(candidate.object_key)
                logger.warning(
                    "Source retention: S3 delete failed kind=%s id=%s key=%s",
                    candidate.kind,
                    candidate.record_id,
                    candidate.object_key,
                    exc_info=True,
                )
                continue

            deleted += 1
            if await self._mark_deleted(candidate):
                marked += 1

        result = SourceRetentionPurgeResult(
            candidates=len(candidates),
            objects_deleted=deleted,
            objects_failed=failed,
            records_marked_deleted=marked,
            failed_keys=failed_keys,
        )
        logger.info(
            "Source retention purge: candidates=%s deleted=%s failed=%s marked=%s",
            result.candidates,
            result.objects_deleted,
            result.objects_failed,
            result.records_marked_deleted,
        )
        return result

    async def _mark_deleted(self, candidate: SourceAssetCandidate) -> bool:
        kind = candidate.kind
        record_id = candidate.record_id
        if kind == "generation_input":
            return await self._repository.mark_generation_input_deleted(job_id=record_id)
        if kind == "generation_archive":
            return await self._repository.mark_generation_archive_deleted(
                job_id=record_id
            )
        if kind == "bulk_zip":
            return await self._repository.mark_bulk_zip_deleted(batch_id=record_id)
        if kind == "bulk_item_input":
            return await self._repository.mark_bulk_item_input_deleted(item_id=record_id)
        if kind == "smart_variant_source":
            return await self._repository.mark_smart_variant_source_deleted(
                sync_id=record_id
            )
        logger.error("Source retention: unknown candidate kind=%s", kind)
        return False
