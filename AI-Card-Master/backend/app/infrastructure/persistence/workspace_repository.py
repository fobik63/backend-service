"""SQLAlchemy workspace persistence adapter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.workspace import (
    SharedGenerationView,
    WorkspaceMemberView,
    WorkspaceRole,
    WorkspaceView,
)
from app.models.generation_job import GenerationJob, GenerationSlide
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSharedGeneration


class WorkspaceRepository:
    """Persist workspaces, memberships, and shared generation assets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_subscription_status(self, user_id: UUID) -> str | None:
        status = await self._session.scalar(
            select(User.subscription_status).where(User.id == user_id)
        )
        if status is None:
            return None
        return str(status.value if hasattr(status, "value") else status)

    async def get_user_email(self, user_id: UUID) -> str | None:
        return await self._session.scalar(select(User.email).where(User.id == user_id))

    async def get_user_id_by_email(self, email: str) -> UUID | None:
        return await self._session.scalar(
            select(User.id).where(func.lower(User.email) == email.lower())
        )

    async def get_workspace_for_owner(self, owner_user_id: UUID) -> WorkspaceView | None:
        workspace = await self._session.scalar(
            select(Workspace)
            .where(Workspace.owner_user_id == owner_user_id)
            .options(selectinload(Workspace.members))
        )
        if workspace is None:
            return None
        return await self._to_workspace_view(workspace)

    async def get_membership_role(
        self, *, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceRole | None:
        role = await self._session.scalar(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if role is None:
            return None
        return WorkspaceRole(str(role))

    async def find_workspace_for_member(self, user_id: UUID) -> WorkspaceView | None:
        workspace_id = await self._session.scalar(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
        )
        if workspace_id is None:
            return None
        workspace = await self._session.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .options(selectinload(Workspace.members))
        )
        if workspace is None:
            return None
        return await self._to_workspace_view(workspace)

    async def is_workspace_manager(self, user_id: UUID) -> bool:
        role = await self._session.scalar(
            select(WorkspaceMember.role).where(WorkspaceMember.user_id == user_id)
        )
        return role == WorkspaceRole.MANAGER.value

    async def create_workspace(
        self,
        *,
        owner_user_id: UUID,
        name: str,
        max_managers: int,
    ) -> WorkspaceView:
        workspace = Workspace(
            owner_user_id=owner_user_id,
            name=name,
            max_managers=max_managers,
        )
        self._session.add(workspace)
        await self._session.flush()
        self._session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner_user_id,
                role=WorkspaceRole.OWNER.value,
            )
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            existing = await self.get_workspace_for_owner(owner_user_id)
            if existing is not None:
                return existing
            raise ValueError("Unable to create workspace.") from exc

        refreshed = await self.get_workspace_for_owner(owner_user_id)
        if refreshed is None:
            raise ValueError("Workspace was created but could not be reloaded.")
        return refreshed

    async def count_managers(self, workspace_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.MANAGER.value,
            )
        )
        return int(count or 0)

    async def add_manager(
        self,
        *,
        workspace_id: UUID,
        manager_user_id: UUID,
        max_managers: int,
    ) -> WorkspaceView:
        workspace = await self._session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise ValueError("Workspace not found.")

        current = await self.count_managers(workspace_id)
        if current >= max_managers:
            raise ValueError(f"Workspace already has the maximum of {max_managers} managers.")

        self._session.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=manager_user_id,
                role=WorkspaceRole.MANAGER.value,
            )
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ValueError("Manager could not be added (already a member).") from exc

        view = await self.find_workspace_for_member(workspace.owner_user_id)
        if view is None:
            raise ValueError("Workspace not found after adding manager.")
        return view

    async def remove_manager(
        self,
        *,
        workspace_id: UUID,
        manager_user_id: UUID,
    ) -> WorkspaceView:
        result = await self._session.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == manager_user_id,
                WorkspaceMember.role == WorkspaceRole.MANAGER.value,
            )
        )
        if result.rowcount == 0:
            await self._session.rollback()
            raise ValueError("Manager membership not found.")
        await self._session.commit()

        workspace = await self._session.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .options(selectinload(Workspace.members))
        )
        if workspace is None:
            raise ValueError("Workspace not found.")
        return await self._to_workspace_view(workspace)

    async def get_owned_generation_job_id(
        self, *, job_id: UUID, owner_user_id: UUID
    ) -> UUID | None:
        return await self._session.scalar(
            select(GenerationJob.id).where(
                GenerationJob.id == job_id,
                GenerationJob.user_id == owner_user_id,
            )
        )

    async def share_generation(
        self,
        *,
        workspace_id: UUID,
        generation_job_id: UUID,
        shared_by_user_id: UUID,
    ) -> SharedGenerationView:
        share = WorkspaceSharedGeneration(
            workspace_id=workspace_id,
            generation_job_id=generation_job_id,
            shared_by_user_id=shared_by_user_id,
        )
        self._session.add(share)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            existing = await self._session.scalar(
                select(WorkspaceSharedGeneration).where(
                    WorkspaceSharedGeneration.workspace_id == workspace_id,
                    WorkspaceSharedGeneration.generation_job_id == generation_job_id,
                )
            )
            if existing is None:
                raise ValueError("Unable to share generation.") from exc
            view = await self.get_share_for_workspace(
                share_id=existing.id, workspace_id=workspace_id
            )
            if view is None:
                raise ValueError("Shared generation could not be loaded.") from exc
            return view

        await self._session.refresh(share)
        view = await self.get_share_for_workspace(
            share_id=share.id, workspace_id=workspace_id
        )
        if view is None:
            raise ValueError("Shared generation could not be loaded.")
        return view

    async def list_shared_generations(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[SharedGenerationView, ...]:
        shares = (
            await self._session.scalars(
                select(WorkspaceSharedGeneration)
                .where(WorkspaceSharedGeneration.workspace_id == workspace_id)
                .order_by(WorkspaceSharedGeneration.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        views: list[SharedGenerationView] = []
        for share in shares:
            view = await self._to_shared_view(share)
            if view is not None:
                views.append(view)
        return tuple(views)

    async def get_share_for_workspace(
        self, *, share_id: UUID, workspace_id: UUID
    ) -> SharedGenerationView | None:
        share = await self._session.scalar(
            select(WorkspaceSharedGeneration).where(
                WorkspaceSharedGeneration.id == share_id,
                WorkspaceSharedGeneration.workspace_id == workspace_id,
            )
        )
        if share is None:
            return None
        return await self._to_shared_view(share)

    async def unshare_generation(
        self,
        *,
        share_id: UUID,
        workspace_id: UUID,
        actor_user_id: UUID,
        actor_is_owner: bool,
    ) -> bool:
        conditions = [
            WorkspaceSharedGeneration.id == share_id,
            WorkspaceSharedGeneration.workspace_id == workspace_id,
        ]
        if not actor_is_owner:
            conditions.append(WorkspaceSharedGeneration.shared_by_user_id == actor_user_id)

        result = await self._session.execute(
            delete(WorkspaceSharedGeneration).where(*conditions)
        )
        if result.rowcount == 0:
            await self._session.rollback()
            return False
        await self._session.commit()
        return True

    async def _to_workspace_view(self, workspace: Workspace) -> WorkspaceView:
        member_rows = sorted(
            workspace.members,
            key=lambda row: (row.role != WorkspaceRole.OWNER.value, row.created_at),
        )
        user_ids = [row.user_id for row in member_rows]
        emails: dict[UUID, str] = {}
        if user_ids:
            result = await self._session.execute(
                select(User.id, User.email).where(User.id.in_(user_ids))
            )
            emails = {row.id: row.email for row in result.all()}

        members = tuple(
            WorkspaceMemberView(
                user_id=row.user_id,
                email=emails.get(row.user_id, ""),
                role=WorkspaceRole(row.role),
                joined_at=row.created_at,
            )
            for row in member_rows
        )
        manager_count = sum(1 for member in members if member.role is WorkspaceRole.MANAGER)
        return WorkspaceView(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            name=workspace.name,
            max_managers=workspace.max_managers,
            manager_count=manager_count,
            members=members,
            created_at=workspace.created_at,
        )

    async def _to_shared_view(
        self, share: WorkspaceSharedGeneration
    ) -> SharedGenerationView | None:
        job = await self._session.scalar(
            select(GenerationJob)
            .where(GenerationJob.id == share.generation_job_id)
            .options(selectinload(GenerationJob.slides))
        )
        if job is None:
            return None
        email = await self.get_user_email(share.shared_by_user_id) or ""
        slide_keys = tuple(
            slide.result_object_key
            for slide in sorted(job.slides, key=lambda item: item.position)
            if isinstance(slide, GenerationSlide) and slide.result_object_key
        )
        return SharedGenerationView(
            share_id=share.id,
            workspace_id=share.workspace_id,
            generation_job_id=share.generation_job_id,
            shared_by_user_id=share.shared_by_user_id,
            shared_by_email=email,
            status=job.status,
            product_category=job.product_category,
            thumbnail_object_key=job.thumbnail_object_key,
            thumbnail_mime_type=job.thumbnail_mime_type,
            archive_object_key=job.archive_object_key,
            slide_result_object_keys=slide_keys,
            shared_at=share.created_at,
            job_created_at=job.created_at,
        )
