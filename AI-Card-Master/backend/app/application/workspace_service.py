"""Application use cases for Pro workspaces and team image sharing."""

from __future__ import annotations

from uuid import UUID

from app.application.ports.workspaces import WorkspacePersistencePort
from app.domain.workspace import (
    DEFAULT_WORKSPACE_MAX_MANAGERS,
    WORKSPACE_OWNER_SUBSCRIPTION_STATUSES,
    SharedGenerationView,
    WorkspaceView,
    normalize_workspace_name,
)


class WorkspaceError(Exception):
    """Base workspace workflow failure."""


class WorkspaceValidationError(WorkspaceError):
    """Workspace request is invalid for the current user state."""


class WorkspaceNotFoundError(WorkspaceError):
    """Requested workspace or related resource was not found."""


class WorkspaceForbiddenError(WorkspaceError):
    """Caller lacks the required workspace role."""


class WorkspaceService:
    """Coordinate Pro workspace membership and shared generation assets."""

    def __init__(
        self,
        repository: WorkspacePersistencePort,
        *,
        max_managers: int = DEFAULT_WORKSPACE_MAX_MANAGERS,
    ) -> None:
        if max_managers <= 0:
            raise WorkspaceValidationError("max_managers must be greater than zero.")
        self._repository = repository
        self._max_managers = max_managers

    async def ensure_workspace(
        self,
        *,
        owner_user_id: UUID,
        name: str | None = None,
    ) -> WorkspaceView:
        """Create or return the Pro owner's workspace."""

        await self._require_pro_owner(owner_user_id)
        existing = await self._repository.get_workspace_for_owner(owner_user_id)
        if existing is not None:
            return existing

        workspace_name = normalize_workspace_name(name or "Team workspace")
        if not workspace_name:
            raise WorkspaceValidationError("Workspace name is required.")
        if len(workspace_name) > 120:
            raise WorkspaceValidationError("Workspace name is too long.")

        return await self._repository.create_workspace(
            owner_user_id=owner_user_id,
            name=workspace_name,
            max_managers=self._max_managers,
        )

    async def get_my_workspace(self, user_id: UUID) -> WorkspaceView:
        """Return the workspace the user owns or joined as a manager."""

        workspace = await self._repository.find_workspace_for_member(user_id)
        if workspace is None:
            raise WorkspaceNotFoundError("User is not a member of any workspace.")
        return workspace

    async def add_manager(
        self,
        *,
        owner_user_id: UUID,
        manager_email: str | None = None,
        manager_user_id: UUID | None = None,
    ) -> WorkspaceView:
        """Attach up to max_managers limited-rights managers to the Pro owner."""

        await self._require_pro_owner(owner_user_id)
        workspace = await self._repository.get_workspace_for_owner(owner_user_id)
        if workspace is None:
            raise WorkspaceNotFoundError("Create a workspace before inviting managers.")

        resolved_manager_id = await self._resolve_manager_user_id(
            manager_email=manager_email,
            manager_user_id=manager_user_id,
        )
        if resolved_manager_id == owner_user_id:
            raise WorkspaceValidationError("Owner cannot be added as a manager.")

        manager_workspace = await self._repository.find_workspace_for_member(
            resolved_manager_id
        )
        if manager_workspace is not None:
            raise WorkspaceValidationError(
                "User already belongs to a workspace and cannot join another."
            )

        try:
            return await self._repository.add_manager(
                workspace_id=workspace.id,
                manager_user_id=resolved_manager_id,
                max_managers=self._max_managers,
            )
        except ValueError as exc:
            raise WorkspaceValidationError(str(exc)) from exc

    async def remove_manager(
        self,
        *,
        owner_user_id: UUID,
        manager_user_id: UUID,
    ) -> WorkspaceView:
        """Detach a manager from the owner's workspace."""

        await self._require_pro_owner(owner_user_id)
        workspace = await self._repository.get_workspace_for_owner(owner_user_id)
        if workspace is None:
            raise WorkspaceNotFoundError("Workspace not found.")
        if manager_user_id == owner_user_id:
            raise WorkspaceValidationError("Owner membership cannot be removed.")

        try:
            return await self._repository.remove_manager(
                workspace_id=workspace.id,
                manager_user_id=manager_user_id,
            )
        except ValueError as exc:
            raise WorkspaceNotFoundError(str(exc)) from exc

    async def share_generation(
        self,
        *,
        user_id: UUID,
        generation_job_id: UUID,
    ) -> SharedGenerationView:
        """Share a generation owned by the caller with their team."""

        workspace = await self._require_membership(user_id)
        owned_job_id = await self._repository.get_owned_generation_job_id(
            job_id=generation_job_id,
            owner_user_id=user_id,
        )
        if owned_job_id is None:
            raise WorkspaceNotFoundError(
                "Generation not found or does not belong to the current user."
            )

        try:
            return await self._repository.share_generation(
                workspace_id=workspace.id,
                generation_job_id=owned_job_id,
                shared_by_user_id=user_id,
            )
        except ValueError as exc:
            raise WorkspaceValidationError(str(exc)) from exc

    async def list_shared_generations(
        self,
        *,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[SharedGenerationView, ...]:
        """List images shared inside the caller's workspace."""

        if limit < 1 or limit > 100:
            raise WorkspaceValidationError("limit must be between 1 and 100.")
        if offset < 0:
            raise WorkspaceValidationError("offset must be >= 0.")

        workspace = await self._require_membership(user_id)
        return await self._repository.list_shared_generations(
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
        )

    async def unshare_generation(
        self,
        *,
        user_id: UUID,
        share_id: UUID,
    ) -> None:
        """Remove a shared image from the team feed."""

        workspace = await self._require_membership(user_id)
        actor_is_owner = workspace.owner_user_id == user_id
        removed = await self._repository.unshare_generation(
            share_id=share_id,
            workspace_id=workspace.id,
            actor_user_id=user_id,
            actor_is_owner=actor_is_owner,
        )
        if not removed:
            raise WorkspaceNotFoundError("Shared generation not found.")

    async def is_billing_blocked_manager(self, user_id: UUID) -> bool:
        """Managers must not access payments / balance endpoints."""

        return await self._repository.is_workspace_manager(user_id)

    async def _require_pro_owner(self, user_id: UUID) -> None:
        status_value = await self._repository.get_user_subscription_status(user_id)
        if status_value is None:
            raise WorkspaceNotFoundError("User not found.")
        if status_value not in WORKSPACE_OWNER_SUBSCRIPTION_STATUSES:
            raise WorkspaceForbiddenError(
                "Only Pro (or higher) account owners can manage workspaces."
            )

    async def _require_membership(self, user_id: UUID) -> WorkspaceView:
        workspace = await self._repository.find_workspace_for_member(user_id)
        if workspace is None:
            raise WorkspaceNotFoundError("User is not a member of any workspace.")
        return workspace

    async def _resolve_manager_user_id(
        self,
        *,
        manager_email: str | None,
        manager_user_id: UUID | None,
    ) -> UUID:
        if manager_user_id is not None and manager_email:
            raise WorkspaceValidationError(
                "Provide either manager_user_id or manager_email, not both."
            )
        if manager_user_id is not None:
            email = await self._repository.get_user_email(manager_user_id)
            if email is None:
                raise WorkspaceNotFoundError("Manager user not found.")
            return manager_user_id

        if not manager_email or not manager_email.strip():
            raise WorkspaceValidationError(
                "manager_email or manager_user_id is required."
            )
        resolved = await self._repository.get_user_id_by_email(manager_email.strip().lower())
        if resolved is None:
            raise WorkspaceNotFoundError("Manager user not found.")
        return resolved
