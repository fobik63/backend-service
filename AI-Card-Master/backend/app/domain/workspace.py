"""Workspace domain primitives independent from persistence and HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

DEFAULT_WORKSPACE_MAX_MANAGERS = 3

# Pro-tier subscriptions that may own a workspace (Start trial is excluded).
WORKSPACE_OWNER_SUBSCRIPTION_STATUSES = frozenset({"Pro", "HalfYear", "Year"})


class WorkspaceRole(StrEnum):
    """Membership role inside a Pro workspace team."""

    OWNER = "owner"
    MANAGER = "manager"

    def can_access_billing(self) -> bool:
        """Managers generate only; billing stays with the Pro owner."""

        return self is WorkspaceRole.OWNER


@dataclass(frozen=True, slots=True)
class WorkspaceMemberView:
    """One team member inside a workspace."""

    user_id: UUID
    email: str
    role: WorkspaceRole
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    """Workspace aggregate returned to API consumers."""

    id: UUID
    owner_user_id: UUID
    name: str
    max_managers: int
    manager_count: int
    members: tuple[WorkspaceMemberView, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SharedGenerationView:
    """A generation job shared with a workspace team."""

    share_id: UUID
    workspace_id: UUID
    generation_job_id: UUID
    shared_by_user_id: UUID
    shared_by_email: str
    status: str
    product_category: str | None
    thumbnail_object_key: str | None
    thumbnail_mime_type: str | None
    archive_object_key: str | None
    slide_result_object_keys: tuple[str, ...]
    shared_at: datetime
    job_created_at: datetime


def normalize_workspace_name(value: str) -> str:
    """Trim and validate a human-readable workspace name."""

    return value.strip()
