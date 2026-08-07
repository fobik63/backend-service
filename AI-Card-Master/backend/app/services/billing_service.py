"""Strict billing: apply successful YooKassa payments to user balance/tariff.

Rules:
- 1 generation = 1 ИИкоин (enforced at spend time elsewhere).
- On successful payment: set subscription_status to the purchased tariff,
  shift subscription_ends_at forward by tariff duration, add coins to balance.
- Webhook processing is idempotent via payment status + yookassa_payment_id.
- Coin debit / freeze: Redis hot path + Postgres ``idempotency_records``
  durable ledger in the same ACID transaction as the balance mutation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.winback import compute_discounted_amount
from app.infrastructure.idempotency_store import (
    STATUS_COMPLETED,
    get_idempotency_record,
    store_completed_response,
)
from app.infrastructure.redis import RedisUnavailableError
from app.models.enums import PaymentStatus, TariffCode
from app.models.idempotency_record import IdempotencyRecord
from app.models.payment import Payment
from app.models.user import User
from app.services.tariffs import TariffPlan, get_tariff_plan


logger = logging.getLogger(__name__)

_BILLING_IDEMPOTENCY_SCOPE_PREFIX = "billing:"


def expected_tariff_amount(
    plan: TariffPlan, *, discount_percent: int | None = None
) -> Decimal:
    """Catalog price, or win-back discounted price when a percent is active."""

    if discount_percent is None:
        return plan.price_rub
    return compute_discounted_amount(plan.price_rub, discount_percent)


def _is_discounted_tariff_amount(catalog_price: Decimal, amount: Decimal) -> bool:
    """Whether ``amount`` equals catalog_price minus a 1–90% win-back discount."""

    if amount <= 0 or amount >= catalog_price:
        return False
    for percent in range(1, 91):
        if compute_discounted_amount(catalog_price, percent) == amount:
            return True
    return False


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


@dataclass(frozen=True, slots=True)
class IdempotentCoinMutationResult:
    """Outcome of an idempotent debit / freeze against the durable ledger."""

    user: User
    already_processed: bool
    response_code: int
    response_body: dict[str, Any]
    idempotency_key: str | None = None


def billing_idempotency_scope(user_id: UUID) -> str:
    """Redis scope isolating financial idempotency keys per user."""

    return f"{_BILLING_IDEMPOTENCY_SCOPE_PREFIX}{user_id}"


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

    async def lookup_idempotency(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
    ) -> IdempotentCoinMutationResult | None:
        """Resolve ``X-Idempotency-Key``: Redis first, Postgres on miss.

        Returns a replay result when the key was already committed for this
        user; ``None`` when the caller must perform the mutation.
        """

        cleaned = idempotency_key.strip()
        if not cleaned:
            raise BillingValidationError("Idempotency key must be non-empty.")

        redis_hit = await self._lookup_idempotency_redis(
            user_id=user_id,
            idempotency_key=cleaned,
        )
        if redis_hit is not None:
            return redis_hit

        pg_hit = await self._lookup_idempotency_postgres(
            user_id=user_id,
            idempotency_key=cleaned,
        )
        if pg_hit is not None:
            await self._cache_idempotency_redis(
                user_id=user_id,
                idempotency_key=cleaned,
                response_code=pg_hit.response_code,
                response_body=pg_hit.response_body,
            )
        return pg_hit

    async def _lookup_idempotency_redis(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
    ) -> IdempotentCoinMutationResult | None:
        try:
            record = await get_idempotency_record(
                scope=billing_idempotency_scope(user_id),
                idempotency_key=idempotency_key,
            )
        except RedisUnavailableError:
            logger.warning(
                "Billing idempotency Redis unavailable; falling back to Postgres",
                exc_info=True,
            )
            return None

        if record is None or record.get("status") != STATUS_COMPLETED:
            return None

        body_raw = record.get("body")
        body: dict[str, Any]
        if isinstance(body_raw, str):
            try:
                parsed = json.loads(body_raw)
                body = parsed if isinstance(parsed, dict) else {"raw": body_raw}
            except (TypeError, ValueError):
                body = {"raw": body_raw}
        elif isinstance(body_raw, dict):
            body = dict(body_raw)
        else:
            body = {}

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        return IdempotentCoinMutationResult(
            user=user,
            already_processed=True,
            response_code=int(record.get("status_code") or 200),
            response_body=body,
            idempotency_key=idempotency_key,
        )

    async def _lookup_idempotency_postgres(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
    ) -> IdempotentCoinMutationResult | None:
        row = await self._session.get(IdempotencyRecord, idempotency_key)
        if row is None:
            return None
        if row.user_id != user_id:
            raise BillingValidationError(
                "Idempotency key belongs to another user."
            )
        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        body = row.response_body if isinstance(row.response_body, dict) else {}
        return IdempotentCoinMutationResult(
            user=user,
            already_processed=True,
            response_code=int(row.response_code),
            response_body=dict(body),
            idempotency_key=idempotency_key,
        )

    async def _persist_idempotency_in_transaction(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
        response_code: int,
        response_body: Mapping[str, Any],
    ) -> None:
        """Insert durable ledger row in the caller's open unit of work."""

        self._session.add(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                user_id=user_id,
                response_code=int(response_code),
                response_body=dict(response_body),
            )
        )
        await self._session.flush()

    async def _cache_idempotency_redis(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
        response_code: int,
        response_body: Mapping[str, Any],
    ) -> None:
        """Best-effort hot-path cache; never fails the ACID commit."""

        settings = get_settings()
        try:
            await store_completed_response(
                scope=billing_idempotency_scope(user_id),
                idempotency_key=idempotency_key,
                status_code=response_code,
                body=json.dumps(
                    dict(response_body),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                media_type="application/json",
                ttl_seconds=settings.idempotency_response_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Could not cache billing idempotency in Redis (durable Postgres ok)",
                exc_info=True,
            )

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
        discount_percent: int | None = None,
    ) -> Payment:
        """Persist a newly created YooKassa payment in pending state."""

        user = await self._session.get(User, user_id)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")

        plan = get_tariff_plan(tariff_code)
        expected = expected_tariff_amount(plan, discount_percent=discount_percent)
        if amount_rub != expected:
            raise BillingValidationError(
                f"Amount mismatch for tariff {tariff_code.value}: "
                f"expected {expected}, got {amount_rub}."
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

        # Trust the amount persisted at checkout (catalog or win-back discount),
        # then require the verified YooKassa amount to match that stored value.
        if expected_amount is not None and expected_amount != payment.amount_rub:
            raise BillingValidationError(
                f"YooKassa amount {expected_amount} does not match stored "
                f"payment amount {payment.amount_rub}."
            )
        if (
            payment.amount_rub != plan.price_rub
            and not _is_discounted_tariff_amount(plan.price_rub, payment.amount_rub)
        ):
            raise BillingValidationError(
                f"Stored payment amount {payment.amount_rub} does not match "
                f"tariff {plan.code.value} price {plan.price_rub} "
                "or a valid win-back discount."
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

        referral_bonus_credited = 0
        if user.referred_by_user_id is not None and user.referral_bonus_granted_at is None:
            referrer = await self._session.get(
                User,
                user.referred_by_user_id,
                with_for_update=True,
            )
            if referrer is not None and referrer.id != user.id:
                referral_bonus_credited = int(get_settings().referral_bonus_coins)
                referrer.ai_coins = int(referrer.ai_coins) + referral_bonus_credited
                user.referral_bonus_granted_at = now

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
        if referral_bonus_credited > 0:
            logger.info(
                "Referral bonus applied: referrer=%s invited_user=%s credits=+%s",
                user.referred_by_user_id,
                user.id,
                referral_bonus_credited,
            )

        from app.domain.audit_log import AuditEventStatus, AuditEventType
        from app.services.audit_events import record_audit_event

        await record_audit_event(
            event_type=AuditEventType.PAYMENT_PURCHASED,
            status=AuditEventStatus.SUCCESS,
            user_id=user.id,
            telegram_id=user.telegram_id,
            actor_type="user",
            message=f"Payment succeeded for tariff {plan.code.value}",
            metadata={
                "payment_id": str(payment.id),
                "yookassa_payment_id": yookassa_payment_id,
                "tariff_code": plan.code.value,
                "coins_credited": plan.ai_coins,
                "amount_rub": str(payment.amount_rub),
            },
        )
        await record_audit_event(
            event_type=AuditEventType.TARIFF_CHANGED,
            status=AuditEventStatus.SUCCESS,
            user_id=user.id,
            telegram_id=user.telegram_id,
            actor_type="system",
            message=f"Tariff set to {user.subscription_status.value}",
            metadata={
                "subscription_status": user.subscription_status.value,
                "subscription_ends_at": new_ends_at.isoformat(),
                "source": "payment",
            },
        )
        if referral_bonus_credited > 0 and user.referred_by_user_id is not None:
            await record_audit_event(
                event_type=AuditEventType.REFERRAL_BONUS_CREDITED,
                status=AuditEventStatus.SUCCESS,
                user_id=user.referred_by_user_id,
                actor_type="system",
                message=f"Referral bonus +{referral_bonus_credited} credits",
                metadata={
                    "invited_user_id": str(user.id),
                    "credits": referral_bonus_credited,
                },
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

    async def debit_coins_in_transaction(
        self,
        *,
        user_id: UUID,
        amount: int,
        idempotency_key: str | None = None,
        response_body: Mapping[str, Any] | None = None,
        response_code: int = 200,
    ) -> User:
        """Debit ``amount`` AI-coins without committing (unit-of-work safe).

        Single write-path for all coin debits (audit R1). Repositories and
        feature services must call this instead of mutating ``User.ai_coins``.

        When ``idempotency_key`` (``X-Idempotency-Key``) is set, Redis is
        checked first and Postgres ``idempotency_records`` on miss. A hit
        returns the locked user without a second debit. A miss writes the
        ledger row in the same flush as the balance change.
        """

        result = await self.debit_coins_idempotent_in_transaction(
            user_id=user_id,
            amount=amount,
            idempotency_key=idempotency_key,
            response_body=response_body,
            response_code=response_code,
        )
        return result.user

    async def debit_coins_idempotent_in_transaction(
        self,
        *,
        user_id: UUID,
        amount: int,
        idempotency_key: str | None = None,
        response_body: Mapping[str, Any] | None = None,
        response_code: int = 200,
        operation: str = "debit",
    ) -> IdempotentCoinMutationResult:
        """Idempotent debit with Redis → Postgres double-check + ACID ledger."""

        if amount < 0:
            raise BillingValidationError("Debit amount must be non-negative.")

        cleaned_key = idempotency_key.strip() if idempotency_key else None
        if cleaned_key:
            replay = await self.lookup_idempotency(
                user_id=user_id,
                idempotency_key=cleaned_key,
            )
            if replay is not None:
                return replay

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")

        # Re-check Postgres under the user row lock (same-user races).
        if cleaned_key:
            locked_replay = await self._lookup_idempotency_postgres(
                user_id=user_id,
                idempotency_key=cleaned_key,
            )
            if locked_replay is not None:
                return locked_replay

        if amount > 0:
            if int(user.ai_coins) < amount:
                raise BillingValidationError("Insufficient AI-coin balance.")
            user.ai_coins = int(user.ai_coins) - amount

        body: dict[str, Any] = {
            "operation": operation,
            "user_id": str(user_id),
            "amount": int(amount),
            "new_balance": int(user.ai_coins),
        }
        if response_body:
            body.update(dict(response_body))

        if cleaned_key:
            try:
                async with self._session.begin_nested():
                    await self._persist_idempotency_in_transaction(
                        user_id=user_id,
                        idempotency_key=cleaned_key,
                        response_code=response_code,
                        response_body=body,
                    )
            except IntegrityError:
                # Concurrent insert won; undo in-session debit and replay.
                if amount > 0:
                    user.ai_coins = int(user.ai_coins) + amount
                race_replay = await self._lookup_idempotency_postgres(
                    user_id=user_id,
                    idempotency_key=cleaned_key,
                )
                if race_replay is not None:
                    return race_replay
                raise BillingValidationError(
                    "Idempotency key conflict could not be resolved."
                ) from None
        else:
            await self._session.flush()

        if cleaned_key:
            await self._cache_idempotency_redis(
                user_id=user_id,
                idempotency_key=cleaned_key,
                response_code=response_code,
                response_body=body,
            )

        return IdempotentCoinMutationResult(
            user=user,
            already_processed=False,
            response_code=int(response_code),
            response_body=body,
            idempotency_key=cleaned_key,
        )

    async def refund_coins_in_transaction(
        self, *, user_id: UUID, amount: int
    ) -> User:
        """Refund ``amount`` AI-coins without committing (unit-of-work safe)."""

        if amount < 0:
            raise BillingValidationError("Refund amount must be non-negative.")
        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        if amount == 0:
            return user
        user.ai_coins = int(user.ai_coins) + amount
        await self._session.flush()
        return user

    async def credit_coins_in_transaction(
        self, *, user_id: UUID, amount: int
    ) -> User:
        """Credit ``amount`` AI-coins without committing (unit-of-work safe)."""

        if amount < 0:
            raise BillingValidationError("Credit amount must be non-negative.")
        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        if amount == 0:
            return user
        user.ai_coins = int(user.ai_coins) + amount
        await self._session.flush()
        return user

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        """Debit coins and commit; return the new balance (``CoinWalletPort``)."""

        user = await self.debit_coins_in_transaction(user_id=user_id, amount=amount)
        await self._session.commit()
        await self._session.refresh(user)
        return int(user.ai_coins)

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        """Refund coins and commit; return the new balance (``CoinWalletPort``)."""

        user = await self.refund_coins_in_transaction(user_id=user_id, amount=amount)
        await self._session.commit()
        await self._session.refresh(user)
        return int(user.ai_coins)

    async def credit_coins(self, *, user_id: UUID, amount: int) -> int:
        """Credit coins and commit; return the new balance (``CoinWalletPort``)."""

        user = await self.credit_coins_in_transaction(user_id=user_id, amount=amount)
        await self._session.commit()
        await self._session.refresh(user)
        return int(user.ai_coins)

    async def debit_generation_coin(self, user_id: UUID) -> int:
        """Spend exactly 1 AI-coin for one generation. Raises if balance is 0."""

        return await self.debit_coins(user_id=user_id, amount=1)

    async def debit_generation_coin_in_transaction(self, user_id: UUID) -> User:
        """Debit one coin without committing the caller's transaction.

        Durable generation creation uses this method so the balance update,
        generation job, and outbox command either commit together or all roll
        back. The original committing method remains available to old callers.
        """

        return await self.debit_coins_in_transaction(user_id=user_id, amount=1)

    async def refund_generation_coin(self, user_id: UUID) -> int:
        """Return 1 AI-coin after a failed generation (Safe Spend companion)."""

        return await self.refund_coins(user_id=user_id, amount=1)

    async def refund_generation_coin_in_transaction(self, user_id: UUID) -> User:
        """Refund one coin without committing the caller's transaction."""

        return await self.refund_coins_in_transaction(user_id=user_id, amount=1)

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
        await self.credit_coins_in_transaction(
            user_id=user_id, amount=int(settings.daily_bonus_coins)
        )
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
