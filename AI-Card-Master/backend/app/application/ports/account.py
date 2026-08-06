"""Ports for GDPR account erasure."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class AccountPersistencePort(Protocol):
    """Load credentials and wipe the user aggregate from the database."""

    async def get_user_credentials(self, user_id: UUID) -> tuple[str, str] | None:
        """Return ``(email, hashed_password)`` or ``None`` if the user is gone."""

        ...

    async def collect_storage_object_keys(self, user_id: UUID) -> list[str]:
        """Return distinct S3 object keys owned by the user."""

        ...

    async def delete_user(self, user_id: UUID) -> bool:
        """Hard-delete the user row (CASCADE related personal data)."""

        ...


class AccountObjectStoragePort(Protocol):
    """Object storage deletes required for right-to-erasure."""

    async def delete_object(self, *, object_key: str) -> None: ...
