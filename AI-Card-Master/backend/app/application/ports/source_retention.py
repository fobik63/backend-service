"""Ports for Zero-Knowledge source retention purge."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.source_retention import SourceAssetCandidate


class SourceRetentionPersistencePort(Protocol):
    """Find and mark heavy source assets past the retention window."""

    async def list_purge_candidates(
        self,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[SourceAssetCandidate]:
        """Return heavy assets still ``available`` and older than ``cutoff``."""

        ...

    async def mark_generation_input_deleted(self, *, job_id: UUID) -> bool:
        """Set generation job input retention status to ``deleted``."""

        ...

    async def mark_generation_archive_deleted(self, *, job_id: UUID) -> bool:
        """Set generation archive retention to ``deleted`` and clear the key."""

        ...

    async def mark_bulk_zip_deleted(self, *, batch_id: UUID) -> bool:
        """Set bulk batch ZIP retention status to ``deleted``."""

        ...

    async def mark_bulk_item_input_deleted(self, *, item_id: UUID) -> bool:
        """Set bulk item original photo retention status to ``deleted``."""

        ...

    async def mark_smart_variant_source_deleted(self, *, sync_id: UUID) -> bool:
        """Set smart-variant source photo retention status to ``deleted``."""

        ...


class SourceRetentionObjectStoragePort(Protocol):
    """Irreversible object deletes for Zero-Knowledge retention."""

    async def delete_object(self, *, object_key: str) -> None: ...
