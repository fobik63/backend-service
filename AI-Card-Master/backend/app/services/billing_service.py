"""Strict billing: apply successful YooKassa payments to user balance/tariff.

Rules:
- 1 generation = 1 ИИкоин (enforced at spend time elsewhere).
- On successful payment: set subscription_status to the purchased tariff,
  shift subscription_ends_at forward by tariff duration, add coins to balance.
- Webhook processing is idempotent via payment status + yookassa_payment_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import PaymentStatus, TariffCode
from app.models.payment import Payment
from app.models.user import User
from app.services.tariffs import TariffPlan, get_tariff_plan


logger = logging.getLogger(__name__)


class BillingError(Exception):
    """Base billing failure."""


class BillingValidationError(BillingError):
    """Invalid billing input or inconsistent payment state."""


class BillingNotFoundError(BillingError):
    """Referenced user or payment was not found."""


@dataclass(frozen=True, slots=True)
class BillingResult:
    """Outcome of applying a successful payment to a user account."""

    payment_id: UUID
    user_id: UUID
    tariff_code: TariffCode
    coins_credited: int
    new_balance: int
    subscription_status: str
    subscription_ends_at: datetime
    already_processed: bool


@dataclass(frozen=True, slots=True)
class DailyBonusResult:
    """Outcome of a once-per-day free AI-coin claim."""

    user_id: UUID
    coins_granted: int
    new_balance: int
    streak: int
    claimed: bool
    last_claimed_at: datetime | None
    next_available_at: datetime


def compute_subscription_end(
    *,
    current_ends_at: datetime | None,
    duration_days: int,
    now: datetime | None = None,
) -> datetime:
    """Shift subscription end date by ``duration_days``.

    If the current subscription is still active, extend from the existing end.
    Otherwise start a fresh window from ``now``.
    """

    if duration_days <= 0:
        raise BillingValidationError("duration_days must be positive.")

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    if current_ends_at is not None:
        end = current_ends_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end > moment:
            return end + timedelta(days=duration_days)

    return moment + timedelta(days=duration_days)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _next_utc_midnight(moment: datetime) -> datetime:
    utc_moment = _to_utc(moment)
    return datetime(
        utc_moment.year,
        utc_moment.month,
        utc_moment.day,
        tzinfo=UTC,
    ) + timedelta(days=1)


class BillingService:
    """Apply tariff purchases and maintain AI-coin balances."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending_payment(
        self,
        *,
        user_id: UUID,
        tariff_code: TariffCode,
        yookassa_payment_id: str,
        amount_rub: Decimal,
        confirmation_url: str | None,
        description: str | None,
        currency: str = "RUB",
    ) -> Payment:
        """Persist a newly created YooKassa payment in pending state."""

        user = await self._session.get(User, user_id)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")

        plan = get_tariff_plan(tariff_code)
        if amount_rub != plan.price_rub:
            raise BillingValidationError(
                f"Amount mismatch for tariff {tariff_code.value}: "
                f"expected {plan.price_rub}, got {amount_rub}."
            )

        existing = await self._session.scalar(
            select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
        )
        if existing is not None:
            raise BillingValidationError(
                f"Payment {yookassa_payment_id} already exists."
            )

        payment = Payment(
            user_id=user_id,
            tariff_code=tariff_code,
            yookassa_payment_id=yookassa_payment_id,
            amount_rub=amount_rub,
            currency=currency,
            status=PaymentStatus.PENDING,
            confirmation_url=confirmation_url,
            description=description,
        )
        self._session.add(payment)
        await self._session.commit()
        await self._session.refresh(payment)
        return payment

    async def get_payment_by_yookassa_id(self, yookassa_payment_id: str) -> Payment | None:
        """Load payment by upstream YooKassa id."""

        return await self._session.scalar(
            select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
        )

    async def mark_payment_canceled(
        self,
        *,
        yookassa_payment_id: str,
        raw_payload: str | None = None,
    ) -> Payment | None:
        """Mark payment as canceled without mutating user balance."""

        payment = await self.get_payment_by_yookassa_id(yookassa_payment_id)
        if payment is None:
            return None
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment

        payment.status = PaymentStatus.CANCELED
        if raw_payload is not None:
            payment.raw_webhook_payload = raw_payload
        await self._session.commit()
        await self._session.refresh(payment)
        return payment

    async def apply_successful_payment(
        self,
        *,
        yookassa_payment_id: str,
        expected_amount: Decimal | None = None,
        raw_payload: str | None = None,
    ) -> BillingResult:
        """Credit coins and update tariff after a verified successful payment.

        Idempotent: repeated calls for an already-succeeded payment return the
        current account state with ``already_processed=True``.
        """

        payment = await self._session.scalar(
            select(Payment)
            .where(Payment.yookassa_payment_id == yookassa_payment_id)
            .with_for_update()
        )
        if payment is None:
            raise BillingNotFoundError(
                f"Payment {yookassa_payment_id} not found in local database."
            )

        if raw_payload is not None:
            payment.raw_webhook_payload = raw_payload

        user = await self._session.get(User, payment.user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {payment.user_id} not found.")

        plan = get_tariff_plan(payment.tariff_code)

        if expected_amount is not None and expected_amount != plan.price_rub:
            raise BillingValidationError(
                f"YooKassa amount {expected_amount} does not match tariff "
                f"{plan.code.value} price {plan.price_rub}."
            )

        if payment.amount_rub != plan.price_rub:
            raise BillingValidationError(
                f"Stored payment amount {payment.amount_rub} does not match "
                f"tariff {plan.code.value} price {plan.price_rub}."
            )

        if payment.status == PaymentStatus.SUCCEEDED and payment.processed_at is not None:
            ends_at = user.subscription_ends_at
            if ends_at is None:
                ends_at = datetime.now(UTC)
            return BillingResult(
                payment_id=payment.id,
                user_id=user.id,
                tariff_code=payment.tariff_code,
                coins_credited=0,
                new_balance=user.ai_coins,
                subscription_status=user.subscription_status.value,
                subscription_ends_at=ends_at,
                already_processed=True,
            )

        now = datetime.now(UTC)
        new_ends_at = compute_subscription_end(
            current_ends_at=user.subscription_ends_at,
            duration_days=plan.duration_days,
            now=now,
        )

        # Strict balance update: never allow negative coin grants from catalog.
        if plan.ai_coins < 0:
            raise BillingValidationError("Tariff ai_coins must be non-negative.")

        user.subscription_status = plan.subscription_status
        user.subscription_ends_at = new_ends_at
        user.ai_coins = int(user.ai_coins) + int(plan.ai_coins)

        payment.status = PaymentStatus.SUCCEEDED
        payment.processed_at = now

        await self._session.commit()
        await self._session.refresh(user)
        await self._session.refresh(payment)

        logger.info(
            "Payment %s applied: user=%s tariff=%s coins=+%s balance=%s ends_at=%s",
            yookassa_payment_id,
            user.id,
            plan.code.value,
            plan.ai_coins,
            user.ai_coins,
            new_ends_at.isoformat(),
        )

        return BillingResult(
            payment_id=payment.id,
            user_id=user.id,
            tariff_code=payment.tariff_code,
            coins_credited=plan.ai_coins,
            new_balance=user.ai_coins,
            subscription_status=user.subscription_status.value,
            subscription_ends_at=new_ends_at,
            already_processed=False,
        )

    async def debit_generation_coin(self, user_id: UUID) -> int:
        """Spend exactly 1 AI-coin for one generation. Raises if balance is 0."""

        user = await self.debit_generation_coin_in_transaction(user_id)
        await self._session.commit()
        await self._session.refresh(user)
        return user.ai_coins

    async def debit_generation_coin_in_transaction(self, user_id: UUID) -> User:
        """Debit one coin without committing the caller's transaction.

        Durable generation creation uses this method so the balance update,
        generation job, and outbox command either commit together or all roll
        back. The original committing method remains available to old callers.
        """

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        if user.ai_coins < 1:
            raise BillingValidationError("Insufficient AI-coin balance.")
        user.ai_coins -= 1
        await self._session.flush()
        return user

    async def refund_generation_coin(self, user_id: UUID) -> int:
        """Return 1 AI-coin after a failed generation (Safe Spend companion)."""

        user = await self.refund_generation_coin_in_transaction(user_id)
        await self._session.commit()
        await self._session.refresh(user)
        return user.ai_coins

    async def refund_generation_coin_in_transaction(self, user_id: UUID) -> User:
        """Refund one coin without committing the caller's transaction."""

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        user.ai_coins = int(user.ai_coins) + 1
        await self._session.flush()
        return user

    async def claim_daily_bonus(self, user_id: UUID) -> DailyBonusResult:
        """Grant the configured daily free coins once per UTC day."""

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")

        settings = get_settings()
        if settings.daily_bonus_coins <= 0:
            raise BillingValidationError("Daily bonus must be greater than zero.")

        now = datetime.now(UTC)
        last_claimed_at = (
            _to_utc(user.daily_bonus_claimed_at)
            if user.daily_bonus_claimed_at is not None
            else None
        )
        next_available_at = _next_utc_midnight(now)

        if last_claimed_at is not None and last_claimed_at.date() == now.date():
            return DailyBonusResult(
                user_id=user.id,
                coins_granted=0,
                new_balance=user.ai_coins,
                streak=user.daily_bonus_streak,
                claimed=False,
                last_claimed_at=last_claimed_at,
                next_available_at=next_available_at,
            )

        yesterday = now.date() - timedelta(days=1)
        streak = (
            int(user.daily_bonus_streak) + 1
            if last_claimed_at is not None and last_claimed_at.date() == yesterday
            else 1
        )
        user.ai_coins = int(user.ai_coins) + int(settings.daily_bonus_coins)
        user.daily_bonus_claimed_at = now
        user.daily_bonus_streak = streak

        await self._session.commit()
        await self._session.refresh(user)

        return DailyBonusResult(
            user_id=user.id,
            coins_granted=settings.daily_bonus_coins,
            new_balance=user.ai_coins,
            streak=user.daily_bonus_streak,
            claimed=True,
            last_claimed_at=user.daily_bonus_claimed_at,
            next_available_at=next_available_at,
        )


def describe_tariff(plan: TariffPlan) -> dict[str, object]:
    """Serialize a tariff plan for API responses."""

    return {
        "code": plan.code.value,
        "title": plan.title,
        "duration_days": plan.duration_days,
        "ai_coins": plan.ai_coins,
        "price_rub": float(plan.price_rub),
        "amount_value": plan.amount_value,
        "subscription_status": plan.subscription_status.value,
        "description": plan.description,
    }
