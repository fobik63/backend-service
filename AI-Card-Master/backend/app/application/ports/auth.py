"""Auth repository port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.models.user import User


class AuthRepositoryPort(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        fingerprint_hash: str | None = None,
        telegram_id: int | None = None,
    ) -> User: ...

    async def link_telegram_id(
        self,
        user_id: UUID,
        *,
        telegram_id: int,
    ) -> User | None:
        """Bind Telegram user id to an existing account."""

        ...

    async def update_fingerprint_hash(
        self,
        user_id: UUID,
        *,
        fingerprint_hash: str,
    ) -> User | None:
        """Persist SHA-256 device fingerprint on the user profile."""

        ...

    async def exists_fingerprint_hash(
        self,
        *,
        fingerprint_hash: str,
        exclude_user_id: UUID | None = None,
    ) -> bool:
        """True when another user row already stores this device fingerprint."""

        ...

    async def flag_user(self, user_id: UUID, *, reason: str) -> User | None:
        """Silently flag an abuser account (no hard ban / no client-visible block)."""

        ...

    async def update_password(
        self,
        user_id: UUID,
        *,
        hashed_password: str,
    ) -> User | None:
        """Replace the stored password hash for an existing user."""

        ...
