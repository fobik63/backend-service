"""Auth repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.models.user import User


class AuthRepositoryPort(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def create_user(self, *, email: str, hashed_password: str) -> User: ...
