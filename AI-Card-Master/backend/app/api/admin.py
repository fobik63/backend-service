"""Admin API endpoints with strict JWT + is_admin access control."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_and_validate_token
from app.core.config import get_settings
from app.models.database import get_db_session
from app.models.enums import SubscriptionStatus
from app.models.user import User
from app.services.admin_service import (
    AdminApiCostStatistics,
    AdminCounterStats,
    AdminErrorLogView,
    AdminNotFoundError,
    AdminPaymentStatistics,
    AdminService,
    AdminStatistics,
    AdminUserView,
    AdminValidationError,
)


bearer_scheme = HTTPBearer(auto_error=False)


class StrictAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class AdminStatisticsResponse(StrictAdminModel):
    """Admin dashboard metrics response."""

    generations_today: int
    generations_last_7_days: int
    total_generations: int
    total_users: int
    registrations_today: int
    registrations_last_7_days: int
    total_payments: int
    successful_payments: int
    total_revenue_rub: Decimal
    active_pro_subscriptions: int
    api_cost_total_usd: Decimal
    midjourney_cost_total_usd: Decimal
    claude_47_cost_total_usd: Decimal


class AdminCounterStatsResponse(StrictAdminModel):
    """Simple counter export response."""

    total: int
    today: int
    last_7_days: int


class AdminPaymentStatsResponse(StrictAdminModel):
    """Payment statistics export response."""

    total: int
    successful: int
    today: int
    last_7_days: int
    total_revenue_rub: Decimal


class AdminApiCostStatsResponse(StrictAdminModel):
    """Third-party API spend export response."""

    events_total: int
    total_cost_usd: Decimal
    midjourney_cost_usd: Decimal
    claude_47_cost_usd: Decimal


class AdminUserResponse(StrictAdminModel):
    """Safe user info exposed in admin endpoints."""

    id: str
    email: str
    is_admin: bool
    subscription_status: SubscriptionStatus
    ai_coins: int
    is_banned: bool
    ban_reason: str | None = None
    banned_at: datetime | None = None
    created_at: datetime


class AdminUpdateSubscriptionRequest(StrictAdminModel):
    """Manual subscription status update payload."""

    email: str = Field(..., min_length=3, max_length=320)
    subscription_status: SubscriptionStatus

    @field_validator("subscription_status", mode="before")
    @classmethod
    def parse_subscription_status(cls, value: object) -> SubscriptionStatus:
        if isinstance(value, SubscriptionStatus):
            return value
        if isinstance(value, str):
            return SubscriptionStatus(value)
        raise ValueError("subscription_status must be a valid subscription value.")


class AdminUserActionRequest(StrictAdminModel):
    """Strict manual moderation/credit action payload."""

    action: Literal["grant_credits", "ban", "unban"]
    user_id: str | None = Field(default=None)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    credits: int | None = Field(default=None, gt=0, le=1_000_000)
    reason: str | None = Field(default=None, min_length=2, max_length=2000)


class AdminCreateErrorLogRequest(StrictAdminModel):
    """Payload for persisting generation error events."""

    source: str = Field(..., min_length=2, max_length=128)
    error_message: str = Field(..., min_length=2, max_length=4000)
    user_id: str | None = Field(default=None)
    context: dict[str, Any] | None = Field(default=None)


class AdminErrorLogResponse(StrictAdminModel):
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
    allowed_user_id = get_settings().admin_allowed_user_id.strip()
    if str(user.id) != allowed_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    return user


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_user)],
    include_in_schema=False,
)


def _admin_user_response(user: AdminUserView) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        subscription_status=SubscriptionStatus(user.subscription_status),
        ai_coins=user.ai_coins,
        is_banned=user.is_banned,
        ban_reason=user.ban_reason,
        banned_at=user.banned_at,
        created_at=user.created_at,
    )


def _parse_optional_user_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id must be a valid UUID.",
        ) from exc


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
            total_generations=stats.total_generations,
            total_users=stats.total_users,
            registrations_today=stats.registrations_today,
            registrations_last_7_days=stats.registrations_last_7_days,
            total_payments=stats.total_payments,
            successful_payments=stats.successful_payments,
            total_revenue_rub=stats.total_revenue_rub,
            active_pro_subscriptions=stats.active_pro_subscriptions,
            api_cost_total_usd=stats.api_cost_total_usd,
            midjourney_cost_total_usd=stats.midjourney_cost_total_usd,
            claude_47_cost_total_usd=stats.claude_47_cost_total_usd,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch admin statistics.",
        ) from exc


@router.get("/stats/registrations", response_model=AdminCounterStatsResponse)
async def get_registration_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminCounterStatsResponse:
    """Export registration counters."""

    stats: AdminCounterStats = await admin_service.get_registration_statistics()
    return AdminCounterStatsResponse(**asdict(stats))


@router.get("/stats/payments", response_model=AdminPaymentStatsResponse)
async def get_payment_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminPaymentStatsResponse:
    """Export payment counters and revenue."""

    stats: AdminPaymentStatistics = await admin_service.get_payment_statistics()
    return AdminPaymentStatsResponse(**asdict(stats))


@router.get("/stats/generations", response_model=AdminCounterStatsResponse)
async def get_generation_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminCounterStatsResponse:
    """Export generation counters."""

    stats: AdminCounterStats = await admin_service.get_generation_statistics()
    return AdminCounterStatsResponse(**asdict(stats))


@router.get("/monitoring/api-costs", response_model=AdminApiCostStatsResponse)
async def get_api_cost_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminApiCostStatsResponse:
    """Export Midjourney and Claude cost counters from database events."""

    stats: AdminApiCostStatistics = await admin_service.get_api_cost_statistics()
    return AdminApiCostStatsResponse(**asdict(stats))


@router.get("/users/by-email", response_model=AdminUserResponse)
async def get_user_by_email(
    email: str = Query(..., min_length=3, max_length=320),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    """Find one user by email for support and moderation actions."""

    try:
        user: AdminUserView = await admin_service.find_user_by_email(email)
        return _admin_user_response(user)
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
        return _admin_user_response(user)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user subscription status.",
        ) from exc


@router.post("/users/actions", response_model=AdminUserResponse)
async def manage_user_action(
    payload: AdminUserActionRequest,
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    """Grant credits or moderate an abusive user."""

    parsed_user_id = _parse_optional_user_id(payload.user_id)
    try:
        if payload.action == "grant_credits":
            if payload.credits is None:
                raise AdminValidationError("credits is required for grant_credits.")
            user = await admin_service.grant_user_credits(
                user_id=parsed_user_id,
                email=payload.email,
                amount=payload.credits,
            )
        elif payload.action == "ban":
            if payload.reason is None:
                raise AdminValidationError("reason is required for ban.")
            user = await admin_service.ban_user(
                user_id=parsed_user_id,
                email=payload.email,
                reason=payload.reason,
            )
        else:
            user = await admin_service.unban_user(
                user_id=parsed_user_id,
                email=payload.email,
            )
        return _admin_user_response(user)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to apply admin user action.",
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
