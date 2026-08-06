"""Workspace persistence port for application-level team workflows."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.workspace import SharedGenerationView, WorkspaceRole, WorkspaceView


class WorkspacePersistencePort(Protocol):
    """Storage operations needed by workspace use cases."""

    async def get_user_subscription_status(self, user_id: UUID) -> str | None:
        """Return subscription_status value or None when the user is missing."""

    async def get_user_email(self, user_id: UUID) -> str | None:
        """Return user email or None when missing."""

    async def get_user_id_by_email(self, email: str) -> UUID | None:
        """Resolve a team invite email to a user id."""

    async def get_workspace_for_owner(self, owner_user_id: UUID) -> WorkspaceView | None:
        """Return the workspace owned by the user, if any."""

    async def get_membership_role(
        self, *, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceRole | None:
        """Return the caller's role in the workspace, or None."""

    async def find_workspace_for_member(self, user_id: UUID) -> WorkspaceView | None:
        """Return the workspace where the user is owner or manager."""

    async def is_workspace_manager(self, user_id: UUID) -> bool:
        """Whether the user is attached as a manager (no billing access)."""

    async def create_workspace(
        self,
        *,
        owner_user_id: UUID,
        name: str,
        max_managers: int,
    ) -> WorkspaceView:
        """Create a workspace and owner membership row."""

    async def count_managers(self, workspace_id: UUID) -> int:
        """Count manager seats currently occupied."""

    async def add_manager(
        self,
        *,
        workspace_id: UUID,
        manager_user_id: UUID,
        max_managers: int,
    ) -> WorkspaceView:
        """Attach a manager to the workspace (enforces seat limit)."""

    async def remove_manager(
        self,
        *,
        workspace_id: UUID,
        manager_user_id: UUID,
    ) -> WorkspaceView:
        """Detach a manager from the workspace."""

    async def get_owned_generation_job_id(
        self, *, job_id: UUID, owner_user_id: UUID
    ) -> UUID | None:
        """Return job id when it belongs to the user, else None."""

    async def share_generation(
        self,
        *,
        workspace_id: UUID,
        generation_job_id: UUID,
        shared_by_user_id: UUID,
    ) -> SharedGenerationView:
        """Share a generation job with the workspace team."""

    async def list_shared_generations(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[SharedGenerationView, ...]:
        """List shared generation assets visible to the team."""

    async def get_share_for_workspace(
        self, *, share_id: UUID, workspace_id: UUID
    ) -> SharedGenerationView | None:
        """Load one share scoped to a workspace."""

    async def unshare_generation(
        self,
        *,
        share_id: UUID,
        workspace_id: UUID,
        actor_user_id: UUID,
        actor_is_owner: bool,
    ) -> bool:
        """Remove a share; owners may remove any, members only their own."""
