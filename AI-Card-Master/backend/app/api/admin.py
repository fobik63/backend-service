"""Admin API endpoints with strict JWT + is_admin access control."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_and_validate_token
from app.models.database import get_db_session
from app.models.enums import SubscriptionStatus
from app.models.user import User
from app.services.admin_service import (
    AdminErrorLogView,
    AdminNotFoundError,
    AdminService,
    AdminStatistics,
    AdminUserView,
    AdminValidationError,
)


bearer_scheme = HTTPBearer(auto_error=False)


class AdminStatisticsResponse(BaseModel):
    """Admin dashboard metrics response."""

    generations_today: int
    generations_last_7_days: int
    total_users: int
    active_pro_subscriptions: int


class AdminUserResponse(BaseModel):
    """Safe user info exposed in admin endpoints."""

    id: str
    email: str
    is_admin: bool
    subscription_status: SubscriptionStatus


class AdminUpdateSubscriptionRequest(BaseModel):
    """Manual subscription status update payload."""

    email: str = Field(..., min_length=3, max_length=320)
    subscription_status: SubscriptionStatus


class AdminCreateErrorLogRequest(BaseModel):
    """Payload for persisting generation error events."""

    source: str = Field(..., min_length=2, max_length=128)
    error_message: str = Field(..., min_length=2, max_length=4000)
    user_id: str | None = Field(default=None)
    context: dict[str, Any] | None = Field(default=None)


class AdminErrorLogResponse(BaseModel):
    """Error log record response for admin troubleshooting."""

    id: str
    user_id: str | None
    source: str
    error_message: str
    context: dict[str, Any] | None
    created_at: datetime


async def get_admin_service(db_session: AsyncSession = Depends(get_db_session)) -> AdminService:
    """Build admin service with request-scoped database session."""

    return AdminService(db_session)


async def require_admin_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """JWT auth dependency that grants access only to users with `is_admin=true`."""

    # 1) Require Bearer token.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2) Verify JWT and mandatory claims.
    try:
        payload = decode_and_validate_token(credentials.credentials, expected_type="access")
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has invalid subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject format is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # 3) Load user and enforce admin-only policy from database.
    stmt = select(User).where(User.id == user_id).limit(1)
    user = await db_session.scalar(stmt)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with token was not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges are required.",
        )

    return user


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_user)],
)


@router.get("/stats", response_model=AdminStatisticsResponse)
async def get_admin_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminStatisticsResponse:
    """Return generation and user subscription statistics."""

    try:
        stats: AdminStatistics = await admin_service.get_statistics()
        return AdminStatisticsResponse(
            generations_today=stats.generations_today,
            generations_last_7_days=stats.generations_last_7_days,
            total_users=stats.total_users,
            active_pro_subscriptions=stats.active_pro_subscriptions,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch admin statistics.",
        ) from exc


@router.get("/users/by-email", response_model=AdminUserResponse)
async def get_user_by_email(
    email: str = Query(..., min_length=3, max_length=320),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    """Find one user by email for support and moderation actions."""

    try:
        user: AdminUserView = await admin_service.find_user_by_email(email)
        return AdminUserResponse(
            id=user.id,
            email=user.email,
            is_admin=user.is_admin,
            subscription_status=SubscriptionStatus(user.subscription_status),
        )
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to find user by email.",
        ) from exc


@router.patch("/users/subscription", response_model=AdminUserResponse)
async def update_user_subscription(
    payload: AdminUpdateSubscriptionRequest,
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    """Update user subscription status manually (for support/reward workflows)."""

    try:
        user: AdminUserView = await admin_service.update_user_subscription_status(
            email=payload.email,
            subscription_status=payload.subscription_status,
        )
        return AdminUserResponse(
            id=user.id,
            email=user.email,
            is_admin=user.is_admin,
            subscription_status=SubscriptionStatus(user.subscription_status),
        )
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user subscription status.",
        ) from exc


@router.get("/generation-errors", response_model=list[AdminErrorLogResponse])
async def list_generation_errors(
    limit: int = Query(default=50, ge=1, le=200),
    admin_service: AdminService = Depends(get_admin_service),
) -> list[AdminErrorLogResponse]:
    """List latest generation errors to monitor service health."""

    try:
        logs = await admin_service.list_generation_error_logs(limit=limit)
        return [
            AdminErrorLogResponse(
                id=item.id,
                user_id=item.user_id,
                source=item.source,
                error_message=item.error_message,
                context=item.context,
                created_at=item.created_at,
            )
            for item in logs
        ]
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch generation error logs.",
        ) from exc


@router.post(
    "/generation-errors",
    response_model=AdminErrorLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_generation_error_log(
    payload: AdminCreateErrorLogRequest,
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminErrorLogResponse:
    """Persist generation failure event manually or from internal tooling."""

    parsed_user_id: UUID | None = None
    if payload.user_id is not None:
        try:
            parsed_user_id = UUID(payload.user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id must be a valid UUID.",
            ) from exc

    try:
        created: AdminErrorLogView = await admin_service.add_generation_error_log(
            source=payload.source,
            error_message=payload.error_message,
            user_id=parsed_user_id,
            context=payload.context,
        )
        return AdminErrorLogResponse(
            id=created.id,
            user_id=created.user_id,
            source=created.source,
            error_message=created.error_message,
            context=created.context,
            created_at=created.created_at,
        )
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save generation error log.",
        ) from exc
