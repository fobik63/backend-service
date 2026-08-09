"""Regression tests for password change use case."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.auth_service import AuthCredentialsError, AuthService
from app.core.security import hash_password, verify_password


class _Repo:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user
        self.updated_hash: str | None = None

    async def get_by_id(self, user_id):  # noqa: ANN001
        if user_id != self.user.id:
            return None
        return self.user

    async def update_password(self, user_id, *, hashed_password: str):  # noqa: ANN001
        if user_id != self.user.id:
            return None
        self.updated_hash = hashed_password
        self.user.hashed_password = hashed_password
        return self.user


class _Uow:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_change_password_updates_hash() -> None:
    user = SimpleNamespace(
        id=uuid4(),
        hashed_password=hash_password("OldPass123!"),
        is_banned=False,
    )
    repo = _Repo(user)
    uow = _Uow()
    service = AuthService(repo, unit_of_work=uow)  # type: ignore[arg-type]

    await service.change_password(
        user.id,
        current_password="OldPass123!",
        new_password="NewPass456!",
    )

    assert uow.committed is True
    assert repo.updated_hash is not None
    assert verify_password("NewPass456!", repo.updated_hash)


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current() -> None:
    user = SimpleNamespace(
        id=uuid4(),
        hashed_password=hash_password("OldPass123!"),
        is_banned=False,
    )
    service = AuthService(_Repo(user), unit_of_work=_Uow())  # type: ignore[arg-type]

    with pytest.raises(AuthCredentialsError):
        await service.change_password(
            user.id,
            current_password="WrongPass!",
            new_password="NewPass456!",
        )
