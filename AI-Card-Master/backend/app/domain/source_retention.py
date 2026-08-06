"""Zero-Knowledge retention for heavy source assets (ZIP + originals)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class SourceRetentionStatus(StrEnum):
    """Lifecycle of heavy user originals / ZIP archives in object storage."""

    AVAILABLE = "available"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class SourceAssetCandidate:
    """One heavy object eligible for irreversible S3 purge."""

    kind: str
    record_id: UUID
    object_key: str
    field_name: str


@dataclass(frozen=True, slots=True)
class SourceRetentionPurgeResult:
    """Outcome of one Celery beat retention sweep."""

    candidates: int = 0
    objects_deleted: int = 0
    objects_failed: int = 0
    records_marked_deleted: int = 0
    failed_keys: list[str] = field(default_factory=list)
