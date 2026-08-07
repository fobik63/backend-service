"""GDPR right-to-erasure use case: delete account and all related data."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.application.ports.account import AccountObjectStoragePort, AccountPersistencePort
from app.core.security import verify_password
from app.domain.account import ACCOUNT_DELETION_CONFIRMATION, AccountDeletionResult

logger = logging.getLogger(__name__)


class AccountError(Exception):
    """Base account workflow failure."""


class AccountNotFoundError(AccountError):
    """User no longer exists."""


class AccountValidationError(AccountError):
    """Password confirmation or erasure payload is invalid."""


class AccountService:
    """Coordinate password confirmation, storage wipe, and DB cascade delete."""

    def __init__(
        self,
        repository: AccountPersistencePort,
        storage: AccountObjectStoragePort,
        *,
        cache_invalidator: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._cache_invalidator = cache_invalidator

    async def delete_account(
        self,
        *,
        user_id: UUID,
        password: str,
        confirmation: str,
    ) -> AccountDeletionResult:
        """Erase the authenticated user's account and personal data."""

        if confirmation.strip() != ACCOUNT_DELETION_CONFIRMATION:
            raise AccountValidationError(
                f'Confirmation must be exactly "{ACCOUNT_DELETION_CONFIRMATION}".'
            )
        if not password:
            raise AccountValidationError("Password is required to delete the account.")

        credentials = await self._repository.get_user_credentials(user_id)
        if credentials is None:
            raise AccountNotFoundError("User not found.")

        email, hashed_password = credentials
        if not verify_password(password, hashed_password):
            raise AccountValidationError("Invalid password.")

        object_keys = await self._repository.collect_storage_object_keys(user_id)
        deleted = 0
        failed = 0
        for object_key in object_keys:
            try:
                await self._storage.delete_object(object_key=object_key)
                deleted += 1
            except Exception:
                failed += 1
                logger.warning(
                    "GDPR erasure: failed to delete storage object user_id=%s key=%s",
                    user_id,
                    object_key,
                    exc_info=True,
                )

        removed = await self._repository.delete_user(user_id)
        if not removed:
            raise AccountNotFoundError("User not found.")

        if self._cache_invalidator is not None:
            try:
                await self._cache_invalidator(user_id)
            except Exception:
                logger.warning(
                    "GDPR erasure: cache invalidation failed user_id=%s",
                    user_id,
                    exc_info=True,
                )

        logger.info(
            "GDPR account erased user_id=%s storage_deleted=%s storage_failed=%s",
            user_id,
            deleted,
            failed,
        )
        from app.domain.audit_log import AuditEventStatus, AuditEventType
        from app.services.audit_events import record_audit_event

        await record_audit_event(
            event_type=AuditEventType.ACCOUNT_DELETED,
            status=AuditEventStatus.SUCCESS,
            user_id=user_id,
            actor_type="user",
            message="Account deleted (GDPR erasure)",
            metadata={
                "storage_deleted": deleted,
                "storage_failed": failed,
            },
        )
        return AccountDeletionResult(
            user_id=user_id,
            email=email,
            storage_objects_deleted=deleted,
            storage_objects_failed=failed,
        )
