"""Unit tests for Pro workspace membership and sharing rules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.workspace_service import (
    WorkspaceForbiddenError,
    WorkspaceService,
    WorkspaceValidationError,
)
from app.domain.workspace import (
    WORKSPACE_OWNER_SUBSCRIPTION_STATUSES,
    WorkspaceMemberView,
    WorkspaceRole,
    WorkspaceView,
)


class FakeWorkspaceRepository:
    """In-memory port stub for workspace use-case tests."""

    def __init__(self) -> None:
        self.subscription_by_user: dict = {}
        self.email_by_user: dict = {}
        self.user_by_email: dict = {}
        self.workspace_by_owner: dict = {}
        self.membership_by_user: dict = {}
        self.managers_by_workspace: dict = {}
        self.owned_jobs: set = set()
        self.shares: dict = {}

    async def get_user_subscription_status(self, user_id):
        return self.subscription_by_user.get(user_id)

    async def get_user_email(self, user_id):
        return self.email_by_user.get(user_id)

    async def get_user_id_by_email(self, email: str):
        return self.user_by_email.get(email.lower())

    async def get_workspace_for_owner(self, owner_user_id):
        return self.workspace_by_owner.get(owner_user_id)

    async def get_membership_role(self, *, workspace_id, user_id):
        workspace = self.membership_by_user.get(user_id)
        if workspace is None or workspace.id != workspace_id:
            return None
        if workspace.owner_user_id == user_id:
            return WorkspaceRole.OWNER
        return WorkspaceRole.MANAGER

    async def find_workspace_for_member(self, user_id):
        return self.membership_by_user.get(user_id)

    async def is_workspace_manager(self, user_id) -> bool:
        workspace = self.membership_by_user.get(user_id)
        return workspace is not None and workspace.owner_user_id != user_id

    async def create_workspace(self, *, owner_user_id, name: str, max_managers: int):
        now = datetime.now(UTC)
        workspace = WorkspaceView(
            id=uuid4(),
            owner_user_id=owner_user_id,
            name=name,
            max_managers=max_managers,
            manager_count=0,
            members=(
                WorkspaceMemberView(
                    user_id=owner_user_id,
                    email=self.email_by_user.get(owner_user_id, "owner@example.com"),
                    role=WorkspaceRole.OWNER,
                    joined_at=now,
                ),
            ),
            created_at=now,
        )
        self.workspace_by_owner[owner_user_id] = workspace
        self.membership_by_user[owner_user_id] = workspace
        self.managers_by_workspace[workspace.id] = []
        return workspace

    async def count_managers(self, workspace_id) -> int:
        return len(self.managers_by_workspace.get(workspace_id, []))

    async def add_manager(self, *, workspace_id, manager_user_id, max_managers: int):
        managers = self.managers_by_workspace.setdefault(workspace_id, [])
        if len(managers) >= max_managers:
            raise ValueError(f"Workspace already has the maximum of {max_managers} managers.")
        owner_id = next(
            wid for wid, ws in self.workspace_by_owner.items() if ws.id == workspace_id
        )
        workspace = self.workspace_by_owner[owner_id]
        now = datetime.now(UTC)
        managers.append(manager_user_id)
        members = list(workspace.members) + [
            WorkspaceMemberView(
                user_id=manager_user_id,
                email=self.email_by_user.get(manager_user_id, "manager@example.com"),
                role=WorkspaceRole.MANAGER,
                joined_at=now,
            )
        ]
        updated = WorkspaceView(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            name=workspace.name,
            max_managers=workspace.max_managers,
            manager_count=len(managers),
            members=tuple(members),
            created_at=workspace.created_at,
        )
        self.workspace_by_owner[owner_id] = updated
        self.membership_by_user[owner_id] = updated
        self.membership_by_user[manager_user_id] = updated
        return updated

    async def remove_manager(self, *, workspace_id, manager_user_id):
        managers = self.managers_by_workspace.get(workspace_id, [])
        if manager_user_id not in managers:
            raise ValueError("Manager membership not found.")
        managers.remove(manager_user_id)
        self.membership_by_user.pop(manager_user_id, None)
        owner_id = next(
            wid for wid, ws in self.workspace_by_owner.items() if ws.id == workspace_id
        )
        workspace = self.workspace_by_owner[owner_id]
        members = tuple(m for m in workspace.members if m.user_id != manager_user_id)
        updated = WorkspaceView(
            id=workspace.id,
            owner_user_id=workspace.owner_user_id,
            name=workspace.name,
            max_managers=workspace.max_managers,
            manager_count=len(managers),
            members=members,
            created_at=workspace.created_at,
        )
        self.workspace_by_owner[owner_id] = updated
        self.membership_by_user[owner_id] = updated
        return updated

    async def get_owned_generation_job_id(self, *, job_id, owner_user_id):
        if (job_id, owner_user_id) in self.owned_jobs:
            return job_id
        return None

    async def share_generation(self, *, workspace_id, generation_job_id, shared_by_user_id):
        from app.domain.workspace import SharedGenerationView

        share_id = uuid4()
        view = SharedGenerationView(
            share_id=share_id,
            workspace_id=workspace_id,
            generation_job_id=generation_job_id,
            shared_by_user_id=shared_by_user_id,
            shared_by_email=self.email_by_user.get(shared_by_user_id, ""),
            status="succeeded",
            product_category="perfume",
            thumbnail_object_key=None,
            thumbnail_mime_type=None,
            archive_object_key=None,
            slide_result_object_keys=(),
            shared_at=datetime.now(UTC),
            job_created_at=datetime.now(UTC),
        )
        self.shares[share_id] = view
        return view

    async def list_shared_generations(self, *, workspace_id, limit: int, offset: int):
        items = [s for s in self.shares.values() if s.workspace_id == workspace_id]
        return tuple(items[offset : offset + limit])

    async def get_share_for_workspace(self, *, share_id, workspace_id):
        share = self.shares.get(share_id)
        if share is None or share.workspace_id != workspace_id:
            return None
        return share

    async def unshare_generation(
        self, *, share_id, workspace_id, actor_user_id, actor_is_owner: bool
    ) -> bool:
        share = self.shares.get(share_id)
        if share is None or share.workspace_id != workspace_id:
            return False
        if not actor_is_owner and share.shared_by_user_id != actor_user_id:
            return False
        del self.shares[share_id]
        return True


@pytest.mark.asyncio
async def test_free_user_cannot_create_workspace() -> None:
    repo = FakeWorkspaceRepository()
    owner_id = uuid4()
    repo.subscription_by_user[owner_id] = "Free"
    service = WorkspaceService(repo, max_managers=3)

    with pytest.raises(WorkspaceForbiddenError):
        await service.ensure_workspace(owner_user_id=owner_id)


@pytest.mark.asyncio
async def test_pro_owner_can_add_up_to_three_managers() -> None:
    repo = FakeWorkspaceRepository()
    owner_id = uuid4()
    repo.subscription_by_user[owner_id] = "Pro"
    repo.email_by_user[owner_id] = "owner@example.com"
    service = WorkspaceService(repo, max_managers=3)

    await service.ensure_workspace(owner_user_id=owner_id, name="Seller Team")

    for index in range(3):
        manager_id = uuid4()
        repo.email_by_user[manager_id] = f"manager{index}@example.com"
        repo.user_by_email[f"manager{index}@example.com"] = manager_id
        repo.subscription_by_user[manager_id] = "Free"
        workspace = await service.add_manager(
            owner_user_id=owner_id,
            manager_email=f"manager{index}@example.com",
        )
        assert workspace.manager_count == index + 1

    fourth = uuid4()
    repo.email_by_user[fourth] = "manager3@example.com"
    repo.user_by_email["manager3@example.com"] = fourth
    with pytest.raises(WorkspaceValidationError):
        await service.add_manager(owner_user_id=owner_id, manager_email="manager3@example.com")


@pytest.mark.asyncio
async def test_manager_is_blocked_from_billing() -> None:
    repo = FakeWorkspaceRepository()
    owner_id = uuid4()
    manager_id = uuid4()
    repo.subscription_by_user[owner_id] = "Pro"
    repo.email_by_user[owner_id] = "owner@example.com"
    repo.email_by_user[manager_id] = "manager@example.com"
    repo.user_by_email["manager@example.com"] = manager_id
    service = WorkspaceService(repo, max_managers=3)

    await service.ensure_workspace(owner_user_id=owner_id)
    await service.add_manager(owner_user_id=owner_id, manager_email="manager@example.com")

    assert await service.is_billing_blocked_manager(manager_id) is True
    assert await service.is_billing_blocked_manager(owner_id) is False


@pytest.mark.asyncio
async def test_team_members_can_share_owned_generation() -> None:
    repo = FakeWorkspaceRepository()
    owner_id = uuid4()
    manager_id = uuid4()
    job_id = uuid4()
    repo.subscription_by_user[owner_id] = "HalfYear"
    repo.email_by_user[owner_id] = "owner@example.com"
    repo.email_by_user[manager_id] = "manager@example.com"
    repo.user_by_email["manager@example.com"] = manager_id
    repo.owned_jobs.add((job_id, manager_id))
    service = WorkspaceService(repo, max_managers=3)

    await service.ensure_workspace(owner_user_id=owner_id)
    await service.add_manager(owner_user_id=owner_id, manager_email="manager@example.com")

    share = await service.share_generation(user_id=manager_id, generation_job_id=job_id)
    listed = await service.list_shared_generations(user_id=owner_id)
    assert len(listed) == 1
    assert listed[0].share_id == share.share_id


def test_workspace_owner_statuses_exclude_start_trial() -> None:
    assert "Start" not in WORKSPACE_OWNER_SUBSCRIPTION_STATUSES
    assert "Pro" in WORKSPACE_OWNER_SUBSCRIPTION_STATUSES
    assert "HalfYear" in WORKSPACE_OWNER_SUBSCRIPTION_STATUSES
    assert "Year" in WORKSPACE_OWNER_SUBSCRIPTION_STATUSES
