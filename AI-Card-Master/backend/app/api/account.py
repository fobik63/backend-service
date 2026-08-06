"""Account self-service API: GDPR right-to-erasure."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.account_service import (
    AccountNotFoundError,
    AccountService,
    AccountValidationError,
)
from app.core.security import InvalidTokenError, decode_and_validate_token
from app.domain.account import ACCOUNT_DELETION_CONFIRMATION
from app.infrastructure.generation_history_cache import invalidate_generation_history_cache
from app.infrastructure.persistence.account_repository import AccountRepository
from app.models.database import get_db_session
from app.models.user import User
from app.services.s3_storage import (
    S3StorageConfigurationError,
    SelectelS3Storage,
    get_s3_storage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["account"])
bearer_scheme = HTTPBearer(auto_error=False)


class DeleteAccountRequest(BaseModel):
    """Password-confirmed GDPR erasure request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    password: str = Field(..., min_length=1, max_length=1024)
    confirmation: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=f'Must be exactly "{ACCOUNT_DELETION_CONFIRMATION}".',
    )


class DeleteAccountResponse(BaseModel):
    """Confirmation that the account and personal data were erased."""

    model_config = ConfigDict(extra="forbid", strict=True)

    deleted: bool = True
    user_id: UUID
    email: str
    storage_objects_deleted: int
    storage_objects_failed: int
    detail: str = (
        "Account and associated personal data have been permanently deleted."
    )


class _NoOpObjectStorage:
    """Used when S3 is not configured; DB erasure still proceeds."""

    async def delete_object(self, *, object_key: str) -> None:
        logger.warning(
            "GDPR erasure: S3 is not configured; skipped object_key=%s",
            object_key,
        )


async def get_current_user_for_erasure(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the JWT subject for erasure, including banned accounts (GDPR)."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_and_validate_token(
            credentials.credentials, expected_type="access"
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is missing.",
        )

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid user id.",
        ) from exc

    user = await db_session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for this token.",
        )
    return user


def _resolve_storage() -> SelectelS3Storage | _NoOpObjectStorage:
    try:
        return get_s3_storage()
    except S3StorageConfigurationError:
        logger.warning("GDPR erasure running without S3 credentials.")
        return _NoOpObjectStorage()


async def get_account_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> AccountService:
    """Request-scoped GDPR erasure service."""

    return AccountService(
        AccountRepository(db_session),
        _resolve_storage(),
        cache_invalidator=invalidate_generation_history_cache,
    )


@router.delete("", response_model=DeleteAccountResponse, status_code=status.HTTP_200_OK)
async def delete_my_account(
    payload: DeleteAccountRequest,
    current_user: User = Depends(get_current_user_for_erasure),
    accounts: AccountService = Depends(get_account_service),
) -> DeleteAccountResponse:
    """Permanently delete the authenticated account and all related personal data (GDPR)."""

    try:
        result = await accounts.delete_account(
            user_id=current_user.id,
            password=payload.password,
            confirmation=payload.confirmation,
        )
    except AccountValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return DeleteAccountResponse(
        deleted=True,
        user_id=result.user_id,
        email=result.email,
        storage_objects_deleted=result.storage_objects_deleted,
        storage_objects_failed=result.storage_objects_failed,
    )
