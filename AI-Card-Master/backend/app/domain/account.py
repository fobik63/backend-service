"""Domain types for GDPR account erasure."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


ACCOUNT_DELETION_CONFIRMATION = "DELETE MY ACCOUNT"


@dataclass(frozen=True, slots=True)
class AccountDeletionResult:
    """Outcome of a successful right-to-erasure request."""

    user_id: UUID
    email: str
    storage_objects_deleted: int
    storage_objects_failed: int
