"""Administrative service for secure operations and platform observability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.cost_analytics_repository import CostAnalyticsRepository
from app.models.enums import PaymentStatus, SubscriptionStatus
from app.models.generation import Generation
from app.models.generation_error_log import GenerationErrorLog
from app.models.generation_job import GenerationJob
from app.models.payment import Payment
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


@dataclass(frozen=True, slots=True)
class AdminCounterStats:
    """Simple total/today/week counter for admin export endpoints."""

    total: int
    today: int
    last_7_days: int


@dataclass(frozen=True, slots=True)
class AdminPaymentStatistics:
    """Aggregated payment counters and paid revenue."""

    total: int
    successful: int
    today: int
    last_7_days: int
    total_revenue_rub: Decimal


@dataclass(frozen=True, slots=True)
class AdminApiCostStatistics:
    """Aggregated third-party API spend."""

    events_total: int
    total_cost_usd: Decimal
    midjourney_cost_usd: Decimal
    claude_47_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class AdminUserView:
    """Safe admin user view model."""

    id: str
    email: str
    is_admin: bool
    subscription_status: str
    ai_coins: int
    is_banned: bool
    ban_reason: str | None
    banned_at: datetime | None
    created_at: datetime


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

        registration_stats = await self.get_registration_statistics()
        payment_stats = await self.get_payment_statistics()
        generation_stats = await self.get_generation_statistics()
        api_cost_stats = await self.get_api_cost_statistics()

        total_users_stmt: Select[tuple[int]] = select(func.count(User.id))
        active_pro_stmt: Select[tuple[int]] = select(func.count(User.id)).where(
            User.subscription_status.in_(
                [
                    SubscriptionStatus.START,
                    SubscriptionStatus.PRO,
                    SubscriptionStatus.HALF_YEAR,
                    SubscriptionStatus.YEAR,
                ]
            )
        )

        total_users_result = await self._db_session.scalar(total_users_stmt)
        active_pro_result = await self._db_session.scalar(active_pro_stmt)

        return AdminStatistics(
            generations_today=generation_stats.today,
            generations_last_7_days=generation_stats.last_7_days,
            total_generations=generation_stats.total,
            total_users=int(total_users_result or 0),
            registrations_today=registration_stats.today,
            registrations_last_7_days=registration_stats.last_7_days,
            total_payments=payment_stats.total,
            successful_payments=payment_stats.successful,
            total_revenue_rub=payment_stats.total_revenue_rub,
            active_pro_subscriptions=int(active_pro_result or 0),
            api_cost_total_usd=api_cost_stats.total_cost_usd,
            midjourney_cost_total_usd=api_cost_stats.midjourney_cost_usd,
            claude_47_cost_total_usd=api_cost_stats.claude_47_cost_usd,
        )

    async def get_registration_statistics(self) -> AdminCounterStats:
        """Return user registration counters."""

        now = datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        week_start = now - timedelta(days=7)
        return AdminCounterStats(
            total=await self._count(User.id),
            today=await self._count(User.id, User.created_at >= today_start),
            last_7_days=await self._count(User.id, User.created_at >= week_start),
        )

    async def get_payment_statistics(self) -> AdminPaymentStatistics:
        """Return payment counters and succeeded payment revenue."""

        now = datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        week_start = now - timedelta(days=7)
        revenue = await self._db_session.scalar(
            select(func.coalesce(func.sum(Payment.amount_rub), 0)).where(
                Payment.status == PaymentStatus.SUCCEEDED
            )
        )
        return AdminPaymentStatistics(
            total=await self._count(Payment.id),
            successful=await self._count(
                Payment.id,
                Payment.status == PaymentStatus.SUCCEEDED,
            ),
            today=await self._count(Payment.id, Payment.created_at >= today_start),
            last_7_days=await self._count(Payment.id, Payment.created_at >= week_start),
            total_revenue_rub=Decimal(str(revenue or "0")),
        )

    async def get_generation_statistics(self) -> AdminCounterStats:
        """Return generation counters across legacy and async-generation tables."""

        now = datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        week_start = now - timedelta(days=7)

        legacy_total = await self._count(Generation.id)
        jobs_total = await self._count(GenerationJob.id)
        legacy_today = await self._count(Generation.id, Generation.created_at >= today_start)
        jobs_today = await self._count(GenerationJob.id, GenerationJob.created_at >= today_start)
        legacy_week = await self._count(Generation.id, Generation.created_at >= week_start)
        jobs_week = await self._count(GenerationJob.id, GenerationJob.created_at >= week_start)
        return AdminCounterStats(
            total=legacy_total + jobs_total,
            today=legacy_today + jobs_today,
            last_7_days=legacy_week + jobs_week,
        )

    async def get_api_cost_statistics(self) -> AdminApiCostStatistics:
        """Return spend totals for Midjourney and Claude via daily rollups (Q1).

        Reads ``api_cost_daily_rollups`` instead of scanning the raw
        ``api_usage_costs`` event table.
        """

        repo = CostAnalyticsRepository(self._db_session)
        # Wide window covers all historical rollup rows without seq-scanning events.
        day_from = date(2020, 1, 1)
        day_to = datetime.now(UTC).date()
        totals = await repo.sum_rollups(day_from=day_from, day_to=day_to)
        by_provider = await repo.sum_rollups_by_provider(
            day_from=day_from,
            day_to=day_to,
        )
        midjourney_cost, _mj_events = by_provider.get(
            "midjourney",
            (Decimal("0"), 0),
        )
        claude_cost, _claude_events = by_provider.get(
            "anthropic",
            (Decimal("0"), 0),
        )
        return AdminApiCostStatistics(
            events_total=totals.events_count,
            total_cost_usd=totals.cost_usd,
            midjourney_cost_usd=midjourney_cost,
            claude_47_cost_usd=claude_cost,
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

    async def grant_user_credits(
        self,
        *,
        user_id: UUID | None,
        email: str | None,
        amount: int,
    ) -> AdminUserView:
        """Add AI credits to a user balance."""

        if amount <= 0:
            raise AdminValidationError("Credit amount must be greater than zero.")
        user = await self._get_user_for_update(user_id=user_id, email=email)
        # Single write-path: BillingService.in_transaction (audit R1).
        from app.services.billing_service import BillingService

        await BillingService(self._db_session).credit_coins_in_transaction(
            user_id=user.id, amount=amount
        )
        await self._db_session.commit()
        await self._db_session.refresh(user)
        return self._to_admin_user_view(user)

    async def ban_user(
        self,
        *,
        user_id: UUID | None,
        email: str | None,
        reason: str,
    ) -> AdminUserView:
        """Ban an abusive user from authenticated product endpoints."""

        normalized_reason = " ".join(reason.strip().split())
        if not normalized_reason:
            raise AdminValidationError("Ban reason cannot be empty.")
        user = await self._get_user_for_update(user_id=user_id, email=email)
        user.is_banned = True
        user.ban_reason = normalized_reason[:2000]
        user.banned_at = datetime.now(UTC)
        await self._db_session.commit()
        await self._db_session.refresh(user)
        return self._to_admin_user_view(user)

    async def unban_user(
        self,
        *,
        user_id: UUID | None,
        email: str | None,
    ) -> AdminUserView:
        """Lift an abuse ban."""

        user = await self._get_user_for_update(user_id=user_id, email=email)
        user.is_banned = False
        user.ban_reason = None
        user.banned_at = None
        await self._db_session.commit()
        await self._db_session.refresh(user)
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

    async def _get_user_for_update(
        self,
        *,
        user_id: UUID | None,
        email: str | None,
    ) -> User:
        if user_id is None and not email:
            raise AdminValidationError("user_id or email is required.")
        if user_id is not None:
            stmt = select(User).where(User.id == user_id).limit(1).with_for_update()
        else:
            normalized_email = (email or "").strip().lower()
            if not normalized_email:
                raise AdminValidationError("Email cannot be empty.")
            stmt = (
                select(User)
                .where(User.email == normalized_email)
                .limit(1)
                .with_for_update()
            )
        user = await self._db_session.scalar(stmt)
        if user is None:
            raise AdminNotFoundError("User not found.")
        return user

    async def _count(self, column: Any, *conditions: Any) -> int:
        stmt = select(func.count(column))
        if conditions:
            stmt = stmt.where(*conditions)
        result = await self._db_session.scalar(stmt)
        return int(result or 0)

    @staticmethod
    def _to_admin_user_view(user: User) -> AdminUserView:
        """Map ORM user model into safe admin response view."""

        return AdminUserView(
            id=str(user.id),
            email=user.email,
            is_admin=bool(user.is_admin),
            subscription_status=user.subscription_status.value,
            ai_coins=int(user.ai_coins or 0),
            is_banned=bool(user.is_banned),
            ban_reason=user.ban_reason,
            banned_at=user.banned_at,
            created_at=user.created_at or datetime.now(UTC),
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
