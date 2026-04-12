"""Administrative service for secure operations and platform observability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubscriptionStatus
from app.models.generation import Generation
from app.models.generation_error_log import GenerationErrorLog
from app.models.user import User


class AdminServiceError(Exception):
    """Base exception for admin service operations."""


class AdminNotFoundError(AdminServiceError):
    """Raised when admin target entity does not exist."""


class AdminValidationError(AdminServiceError):
    """Raised when admin input is invalid."""


@dataclass(frozen=True, slots=True)
class AdminStatistics:
    """Aggregated metrics for admin dashboard."""

    generations_today: int
    generations_last_7_days: int
    total_users: int
    active_pro_subscriptions: int


@dataclass(frozen=True, slots=True)
class AdminUserView:
    """Safe admin user view model."""

    id: str
    email: str
    is_admin: bool
    subscription_status: str


@dataclass(frozen=True, slots=True)
class AdminErrorLogView:
    """Safe error log view model."""

    id: str
    user_id: str | None
    source: str
    error_message: str
    context: dict[str, Any] | None
    created_at: datetime


class AdminService:
    """Secure admin operations using async SQLAlchemy session."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def get_statistics(self) -> AdminStatistics:
        """Return dashboard statistics for day/week activity and subscription data."""

        now = datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        week_start = now - timedelta(days=7)

        generations_today_stmt: Select[tuple[int]] = select(func.count(Generation.id)).where(
            Generation.created_at >= today_start
        )
        generations_week_stmt: Select[tuple[int]] = select(func.count(Generation.id)).where(
            Generation.created_at >= week_start
        )
        total_users_stmt: Select[tuple[int]] = select(func.count(User.id))
        active_pro_stmt: Select[tuple[int]] = select(func.count(User.id)).where(
            User.subscription_status == SubscriptionStatus.PRO
        )

        generations_today_result = await self._db_session.scalar(generations_today_stmt)
        generations_week_result = await self._db_session.scalar(generations_week_stmt)
        total_users_result = await self._db_session.scalar(total_users_stmt)
        active_pro_result = await self._db_session.scalar(active_pro_stmt)

        return AdminStatistics(
            generations_today=int(generations_today_result or 0),
            generations_last_7_days=int(generations_week_result or 0),
            total_users=int(total_users_result or 0),
            active_pro_subscriptions=int(active_pro_result or 0),
        )

    async def find_user_by_email(self, email: str) -> AdminUserView:
        """Find user by normalized email."""

        normalized_email = email.strip().lower()
        if not normalized_email:
            raise AdminValidationError("Email cannot be empty.")

        stmt: Select[tuple[User]] = select(User).where(User.email == normalized_email).limit(1)
        user = await self._db_session.scalar(stmt)
        if user is None:
            raise AdminNotFoundError("User not found.")

        return self._to_admin_user_view(user)

    async def update_user_subscription_status(
        self,
        email: str,
        subscription_status: SubscriptionStatus,
    ) -> AdminUserView:
        """Update user subscription status manually by email."""

        normalized_email = email.strip().lower()
        if not normalized_email:
            raise AdminValidationError("Email cannot be empty.")

        stmt: Select[tuple[User]] = select(User).where(User.email == normalized_email).limit(1)
        user = await self._db_session.scalar(stmt)
        if user is None:
            raise AdminNotFoundError("User not found.")

        user.subscription_status = subscription_status
        await self._db_session.commit()
        await self._db_session.refresh(user)

        return self._to_admin_user_view(user)

    async def add_generation_error_log(
        self,
        source: str,
        error_message: str,
        user_id: UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> AdminErrorLogView:
        """Persist generation failure details for troubleshooting."""

        normalized_source = source.strip()
        normalized_message = error_message.strip()
        if not normalized_source:
            raise AdminValidationError("Error source cannot be empty.")
        if not normalized_message:
            raise AdminValidationError("Error message cannot be empty.")

        error_log = GenerationErrorLog(
            user_id=user_id,
            source=normalized_source,
            error_message=normalized_message,
            context=context,
        )
        self._db_session.add(error_log)
        await self._db_session.commit()
        await self._db_session.refresh(error_log)

        return self._to_error_log_view(error_log)

    async def list_generation_error_logs(self, limit: int = 50) -> list[AdminErrorLogView]:
        """Return latest generation error logs for admin monitoring."""

        if limit <= 0:
            raise AdminValidationError("Limit must be greater than zero.")

        stmt: Select[tuple[GenerationErrorLog]] = (
            select(GenerationErrorLog)
            .order_by(GenerationErrorLog.created_at.desc())
            .limit(min(limit, 200))
        )
        rows = await self._db_session.scalars(stmt)

        return [self._to_error_log_view(item) for item in rows.all()]

    @staticmethod
    def _to_admin_user_view(user: User) -> AdminUserView:
        """Map ORM user model into safe admin response view."""

        return AdminUserView(
            id=str(user.id),
            email=user.email,
            is_admin=bool(user.is_admin),
            subscription_status=user.subscription_status.value,
        )

    @staticmethod
    def _to_error_log_view(item: GenerationErrorLog) -> AdminErrorLogView:
        """Map ORM error log model into safe admin response view."""

        return AdminErrorLogView(
            id=str(item.id),
            user_id=str(item.user_id) if item.user_id else None,
            source=item.source,
            error_message=item.error_message,
            context=item.context,
            created_at=item.created_at,
        )
