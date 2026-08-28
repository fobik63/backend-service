"""CoinGuardService: validate, freeze, stepwise capture, and refund AI-coins.

Layers:
1. Strict integer input validation (no negatives, zero, floats, overflow).
2. Pessimistic ``SELECT … FOR UPDATE`` + idempotent wallet debit + audit row
   in one unit of work.
3. Zero / insufficient balance → HTTP 402 with ``missing_coins``.
4. Batch hold + per-LLM-step capture; rollback remaining without going negative.
5. Per-account spend rate limit and banned/frozen gates before balance math.

Balance mutations always go through ``BillingService`` (audit R1 / FOR UPDATE).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.pricing import CoinHoldStatus
from app.domain.audit_log import AuditEventRecord, AuditEventStatus, AuditEventType
from app.domain.coin_guard import (
    DEFAULT_MAX_OPERATION_COINS,
    DEFAULT_RATE_WINDOW_SECONDS,
    DEFAULT_SPEND_PER_MINUTE,
    PG_INT32_MAX,
    AccountBlockedError,
    AccountFrozenError,
    BatchSpendResult,
    CoinAccountNotFoundError,
    CoinAmountInvalidError,
    CoinGuardError,
    CoinHoldConflictError,
    CoinIdempotencyConflictError,
    CoinOperationKind,
    CoinRateLimitError,
    HoldResult,
    InsufficientBalanceError,
    SpendResult,
    ZeroBalanceError,
    parse_idempotency_uuid,
    parse_positive_coin_amount,
    safe_multiply_coins,
)
from app.infrastructure.persistence.audit_log_repository import AuditLogRepository
from app.infrastructure.redis import RedisUnavailableError, get_security_redis_client
from app.models.coin_hold import CoinHold
from app.models.user import User
from app.services.billing_service import (
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
    IdempotentCoinMutationResult,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

BATCH_STOP_LLM_FAILURE: str = "llm_failure"
_STEP_NAMESPACE = UUID("00000000-0000-4000-8000-0000000000c0")


class CoinSpendRateLimiter(Protocol):
    async def assert_allowed(self, account_id: UUID) -> None: ...


class RedisCoinSpendRateLimiter:
    """Fixed-window counter per ``account_id`` on the security Redis store."""

    def __init__(
        self,
        *,
        limit: int = DEFAULT_SPEND_PER_MINUTE,
        window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS,
    ) -> None:
        self._limit = max(1, int(limit))
        self._window = max(1, int(window_seconds))

    async def assert_allowed(self, account_id: UUID) -> None:
        key = f"coin_guard:spend:{account_id}"
        try:
            client = get_security_redis_client()
            count = int(await client.incr(key))
            if count == 1:
                await client.expire(key, self._window)
            ttl = int(await client.ttl(key))
        except (RedisUnavailableError, OSError, ConnectionError):
            logger.warning(
                "CoinGuard rate limiter Redis unavailable; allowing request",
                exc_info=True,
            )
            return
        except Exception:
            logger.warning(
                "CoinGuard rate limiter failed open; allowing request",
                exc_info=True,
            )
            return
        if count > self._limit:
            retry_after = ttl if ttl > 0 else self._window
            raise CoinRateLimitError(
                "Слишком много операций списания с этого аккаунта. "
                "Повторите попытку позже.",
                retry_after_seconds=retry_after,
            )


class MemoryCoinSpendRateLimiter:
    """Process-local limiter for tests (same semantics as the Redis window)."""

    def __init__(
        self,
        *,
        limit: int = DEFAULT_SPEND_PER_MINUTE,
        window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._limit = max(1, int(limit))
        self._window = max(1, int(window_seconds))
        self._clock = clock or time.monotonic
        self._buckets: dict[UUID, tuple[float, int]] = {}

    async def assert_allowed(self, account_id: UUID) -> None:
        now = self._clock()
        started, count = self._buckets.get(account_id, (now, 0))
        if now - started >= self._window:
            started, count = now, 0
        count += 1
        self._buckets[account_id] = (started, count)
        if count > self._limit:
            raise CoinRateLimitError(
                "Слишком много операций списания с этого аккаунта. "
                "Повторите попытку позже.",
                retry_after_seconds=self._window,
            )


def _batch_step_uuid(batch_key: str, suffix: str) -> UUID:
    return uuid5(_STEP_NAMESPACE, f"{batch_key}:{suffix}")


class CoinGuardService:
    """Transactional guard for hold / stepwise spend / rollback of AI-coins."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        billing: BillingService | None = None,
        rate_limiter: CoinSpendRateLimiter | None = None,
        settings: Settings | None = None,
        auto_commit: bool = False,
    ) -> None:
        self._session = session
        self._billing = billing or BillingService(session)
        self._settings = settings
        self._auto_commit = bool(auto_commit)
        self._rate_limiter = rate_limiter

    def _resolved_settings(self) -> Any:
        return self._settings if self._settings is not None else get_settings()

    @property
    def max_operation_coins(self) -> int:
        settings = self._resolved_settings()
        raw = getattr(
            settings, "coin_guard_max_operation_coins", DEFAULT_MAX_OPERATION_COINS
        )
        return min(int(raw), PG_INT32_MAX)

    def _limiter(self) -> CoinSpendRateLimiter:
        if self._rate_limiter is not None:
            return self._rate_limiter
        settings = self._resolved_settings()
        self._rate_limiter = RedisCoinSpendRateLimiter(
            limit=int(
                getattr(
                    settings, "coin_guard_spend_per_minute", DEFAULT_SPEND_PER_MINUTE
                )
            ),
            window_seconds=int(
                getattr(
                    settings,
                    "coin_guard_rate_window_seconds",
                    DEFAULT_RATE_WINDOW_SECONDS,
                )
            ),
        )
        return self._rate_limiter

    def validate_amount(
        self,
        amount: object,
        *,
        kind: CoinOperationKind = "spend",
    ) -> int:
        return parse_positive_coin_amount(
            amount,
            max_operation_coins=self.max_operation_coins,
            kind=kind,
        )

    async def validate_and_hold(
        self,
        *,
        account_id: UUID,
        amount: object,
        idempotency_key: UUID | str,
        service_type: str | None = None,
        reference_id: UUID | None = None,
        unit_cost: object | None = None,
        units: int | None = None,
    ) -> HoldResult:
        """Freeze ``amount`` (or ``unit_cost * units``) under a row lock.

        Replays with the same UUID return the prior hold without a second debit.
        """

        cleaned_key = parse_idempotency_uuid(idempotency_key)
        if units is not None:
            unit = self.validate_amount(
                unit_cost if unit_cost is not None else amount, kind="hold"
            )
            total = safe_multiply_coins(
                unit,
                int(units),
                max_operation_coins=self.max_operation_coins,
            )
        else:
            total = self.validate_amount(amount, kind="hold")

        replay = await self._replay_hold(
            account_id=account_id, idempotency_key=cleaned_key
        )
        if replay is not None:
            return replay

        await self._limiter().assert_allowed(account_id)

        user = await self._lock_and_authorize(account_id)
        self._assert_sufficient(user=user, required=total)

        existing_hold = await self._hold_by_idempotency(cleaned_key)
        if existing_hold is not None:
            if existing_hold.user_id != account_id:
                raise CoinIdempotencyConflictError(
                    "Ключ идемпотентности уже использован другой учётной записью."
                )
            return self._hold_result_from_row(
                existing_hold, new_balance=int(user.ai_coins), already_processed=True
            )

        hold = CoinHold(
            id=uuid4(),
            user_id=account_id,
            amount=total,
            remaining_amount=total,
            captured_amount=0,
            status=CoinHoldStatus.HELD.value,
            service_type=(
                service_type.strip().lower() if service_type else "coin_guard"
            ),
            reference_id=reference_id,
            idempotency_key=cleaned_key,
        )
        self._session.add(hold)

        try:
            mutation = await self._billing.debit_coins_idempotent_in_transaction(
                user_id=account_id,
                amount=total,
                idempotency_key=cleaned_key,
                response_body=self._hold_ledger_body(hold),
                response_code=200,
                operation="hold",
            )
        except BillingNotFoundError as exc:
            await self._discard_unflushed_hold(hold)
            raise CoinAccountNotFoundError("Пользователь не найден.") from exc
        except BillingValidationError as exc:
            await self._discard_unflushed_hold(hold)
            self._reraise_billing(exc, required=total, user=user)

        if mutation.already_processed:
            await self._discard_unflushed_hold(hold)
            return self._hold_result_from_replay(account_id, mutation)

        await self._append_audit(
            user_id=account_id,
            event_type=AuditEventType.CREDIT_DEDUCTED,
            message=f"Заморозка {total} ИИ-коинов (hold {hold.id})",
            metadata={
                "hold_id": str(hold.id),
                "amount": total,
                "operation": "hold",
                "idempotency_key": cleaned_key,
                "new_balance": int(mutation.user.ai_coins),
            },
        )
        await self._session.flush()
        await self._finish_write()
        return HoldResult(
            hold_id=hold.id,
            account_id=account_id,
            amount_held=total,
            remaining_amount=int(hold.remaining_amount),
            captured_amount=int(hold.captured_amount),
            new_balance=int(mutation.user.ai_coins),
            status=str(hold.status),
            already_processed=False,
            idempotency_key=cleaned_key,
        )

    async def commit_spend(
        self,
        *,
        hold_id: UUID,
        amount: object,
        idempotency_key: UUID | str | None = None,
    ) -> SpendResult:
        """Capture ``amount`` from an existing hold (no extra debit).

        Used after a successful LLM unit. Remaining coins stay frozen.
        """

        step = self.validate_amount(amount, kind="spend")
        step_key = (
            parse_idempotency_uuid(idempotency_key)
            if idempotency_key is not None
            else None
        )

        hold = await self._lock_hold(hold_id)
        if step_key:
            replay = await self._replay_spend(
                account_id=hold.user_id, idempotency_key=step_key, hold=hold
            )
            if replay is not None:
                return replay

        if hold.status != CoinHoldStatus.HELD.value:
            raise CoinHoldConflictError(
                "Нельзя списать шаг: заморозка уже закрыта.",
                hold_id=hold.id,
            )
        remaining = int(hold.remaining_amount)
        if step > remaining:
            raise CoinHoldConflictError(
                "Сумма шага превышает незахваченный остаток заморозки.",
                hold_id=hold.id,
            )

        hold.remaining_amount = remaining - step
        hold.captured_amount = int(hold.captured_amount) + step
        now = datetime.now(UTC)
        hold.updated_at = now
        if int(hold.remaining_amount) == 0:
            hold.status = CoinHoldStatus.CAPTURED.value
            hold.settled_at = now

        user = await self._session.get(User, hold.user_id, with_for_update=True)
        if user is None:
            raise CoinAccountNotFoundError("Пользователь не найден.")

        if step_key:
            await self._billing.debit_coins_idempotent_in_transaction(
                user_id=hold.user_id,
                amount=0,
                idempotency_key=step_key,
                response_body=self._spend_ledger_body(hold, step=step),
                response_code=200,
                operation="commit_spend",
            )

        await self._append_audit(
            user_id=hold.user_id,
            event_type=AuditEventType.CREDIT_DEDUCTED,
            message=f"Захват {step} ИИ-коинов из hold {hold.id}",
            metadata={
                "hold_id": str(hold.id),
                "step_amount": step,
                "remaining_amount": int(hold.remaining_amount),
                "captured_amount": int(hold.captured_amount),
                "operation": "commit_spend",
            },
        )
        await self._session.flush()
        await self._finish_write()
        return self._spend_result(
            hold,
            step=step,
            refunded=0,
            new_balance=int(user.ai_coins),
            already_processed=False,
        )

    async def rollback_spend(
        self,
        *,
        hold_id: UUID,
        idempotency_key: UUID | str | None = None,
    ) -> SpendResult:
        """Refund uncaptured coins; keep already captured spend and generated work."""

        step_key = (
            parse_idempotency_uuid(idempotency_key)
            if idempotency_key is not None
            else None
        )
        hold = await self._lock_hold(hold_id)
        if step_key:
            replay = await self._replay_spend(
                account_id=hold.user_id, idempotency_key=step_key, hold=hold
            )
            if replay is not None:
                return replay

        terminal = {
            CoinHoldStatus.REFUNDED.value,
            CoinHoldStatus.CAPTURED.value,
            CoinHoldStatus.PARTIALLY_SETTLED.value,
        }
        user = await self._session.get(User, hold.user_id, with_for_update=True)
        if user is None:
            raise CoinAccountNotFoundError("Пользователь не найден.")

        if hold.status in terminal:
            return self._spend_result(
                hold,
                step=0,
                refunded=0,
                new_balance=int(user.ai_coins),
                already_processed=True,
            )
        if hold.status != CoinHoldStatus.HELD.value:
            raise CoinHoldConflictError(
                "Нельзя откатить заморозку в текущем статусе.",
                hold_id=hold.id,
            )

        refund_amount = int(hold.remaining_amount)
        if refund_amount > 0:
            try:
                user = await self._billing.refund_coins_in_transaction(
                    user_id=hold.user_id,
                    amount=refund_amount,
                    idempotency_key=step_key,
                    response_body=self._spend_ledger_body(
                        hold,
                        step=refund_amount,
                        operation="rollback_spend",
                    ),
                )
            except BillingNotFoundError as exc:
                raise CoinAccountNotFoundError("Пользователь не найден.") from exc

        now = datetime.now(UTC)
        hold.remaining_amount = 0
        hold.updated_at = now
        hold.settled_at = now
        if int(hold.captured_amount) > 0:
            hold.status = CoinHoldStatus.PARTIALLY_SETTLED.value
        else:
            hold.status = CoinHoldStatus.REFUNDED.value

        await self._append_audit(
            user_id=hold.user_id,
            event_type=AuditEventType.CREDIT_REFUNDED,
            message=(
                f"Возврат {refund_amount} ИИ-коинов по hold {hold.id} "
                f"(захвачено {int(hold.captured_amount)})"
            ),
            metadata={
                "hold_id": str(hold.id),
                "refunded_amount": refund_amount,
                "captured_amount": int(hold.captured_amount),
                "operation": "rollback_spend",
            },
        )
        await self._session.flush()
        await self._finish_write()
        return self._spend_result(
            hold,
            step=refund_amount,
            refunded=refund_amount,
            new_balance=int(user.ai_coins),
            already_processed=False,
        )

    async def run_batch(
        self,
        *,
        account_id: UUID,
        unit_cost: object,
        items: Sequence[T],
        generate_one: Callable[[T], Awaitable[R]],
        persist: Callable[[], Awaitable[None]] | None = None,
        idempotency_key: UUID | str,
        service_type: str = "llm_batch",
    ) -> tuple[BatchSpendResult, tuple[R, ...]]:
        """Freeze the full batch, capture per successful LLM unit, refund the rest."""

        unit = self.validate_amount(unit_cost, kind="hold")
        requested = len(items)
        if requested < 1:
            raise CoinAmountInvalidError("Пакетная операция не содержит элементов.")

        base_key = parse_idempotency_uuid(idempotency_key)
        hold = await self.validate_and_hold(
            account_id=account_id,
            amount=unit,
            units=requested,
            unit_cost=unit,
            idempotency_key=base_key,
            service_type=service_type,
        )
        produced: list[R] = []
        stopped: str | None = None

        for index, item in enumerate(items):
            capture_key = _batch_step_uuid(base_key, f"commit:{index}")
            try:
                generated = await generate_one(item)
            except Exception:
                stopped = BATCH_STOP_LLM_FAILURE
                await self.rollback_spend(
                    hold_id=hold.hold_id,
                    idempotency_key=_batch_step_uuid(base_key, "rollback"),
                )
                if persist is not None:
                    await persist()
                return await self._batch_snapshot(
                    hold_id=hold.hold_id,
                    account_id=account_id,
                    requested=requested,
                    committed=len(produced),
                    unit=unit,
                    stopped=stopped,
                ), tuple(produced)
            await self.commit_spend(
                hold_id=hold.hold_id,
                amount=unit,
                idempotency_key=capture_key,
            )
            if persist is not None:
                await persist()
            produced.append(generated)

        return await self._batch_snapshot(
            hold_id=hold.hold_id,
            account_id=account_id,
            requested=requested,
            committed=len(produced),
            unit=unit,
            stopped=None,
        ), tuple(produced)

    async def _batch_snapshot(
        self,
        *,
        hold_id: UUID,
        account_id: UUID,
        requested: int,
        committed: int,
        unit: int,
        stopped: str | None,
    ) -> BatchSpendResult:
        settled = await self._lock_hold(hold_id)
        user = await self._session.get(User, account_id)
        refunded = max(0, unit * (requested - committed))
        if stopped is None:
            refunded = int(0)
        return BatchSpendResult(
            hold_id=hold_id,
            account_id=account_id,
            units_requested=requested,
            units_committed=committed,
            coins_captured=int(settled.captured_amount),
            coins_refunded=refunded,
            new_balance=int(user.ai_coins) if user is not None else 0,
            status=str(settled.status),
            stopped_reason=stopped,
        )

    async def _lock_and_authorize(self, account_id: UUID) -> User:
        user = await self._session.get(User, account_id, with_for_update=True)
        if user is None:
            raise CoinAccountNotFoundError("Пользователь не найден.")
        if bool(getattr(user, "is_banned", False)):
            raise AccountBlockedError(
                "Аккаунт заблокирован. Операции с балансом запрещены."
            )
        if bool(getattr(user, "is_frozen", False)):
            raise AccountFrozenError(
                "Аккаунт заморожен. Операции с балансом временно недоступны."
            )
        return user

    def _assert_sufficient(self, *, user: User, required: int) -> None:
        balance = int(getattr(user, "ai_coins", 0) or 0)
        if balance <= 0:
            raise ZeroBalanceError(
                f"Нулевой баланс. Для операции требуется {required} коинов.",
                required_coins=required,
                balance=0,
                missing_coins=required,
            )
        if balance < required:
            missing = required - balance
            raise InsufficientBalanceError(
                f"Недостаточно коинов: на балансе {balance}, требуется {required}, "
                f"дефицит {missing}.",
                required_coins=required,
                balance=balance,
                missing_coins=missing,
            )

    def _reraise_billing(
        self,
        exc: BillingValidationError,
        *,
        required: int,
        user: User,
    ) -> None:
        message = str(exc).lower()
        if "idempotency key belongs to another user" in message:
            raise CoinIdempotencyConflictError(
                "Ключ идемпотентности уже использован другой учётной записью."
            ) from exc
        if "insufficient" in message:
            balance = int(getattr(user, "ai_coins", 0) or 0)
            if balance <= 0:
                raise ZeroBalanceError(
                    f"Нулевой баланс. Для операции требуется {required} коинов.",
                    required_coins=required,
                    balance=0,
                    missing_coins=required,
                ) from exc
            raise InsufficientBalanceError(
                f"Недостаточно коинов: на балансе {balance}, требуется {required}, "
                f"дефицит {required - balance}.",
                required_coins=required,
                balance=balance,
                missing_coins=max(0, required - balance),
            ) from exc
        raise CoinGuardError(str(exc)) from exc

    async def _lock_hold(self, hold_id: UUID) -> CoinHold:
        hold = await self._session.get(CoinHold, hold_id, with_for_update=True)
        if hold is None:
            raise CoinHoldConflictError("Заморозка коинов не найдена.")
        return hold

    async def _hold_by_idempotency(self, idempotency_key: str) -> CoinHold | None:
        getter = getattr(self._session, "scalar", None)
        if callable(getter):
            return await self._session.scalar(
                select(CoinHold).where(CoinHold.idempotency_key == idempotency_key)
            )
        holds = getattr(self._session, "holds", None)
        if isinstance(holds, dict):
            for hold in holds.values():
                if getattr(hold, "idempotency_key", None) == idempotency_key:
                    return hold
        return None

    async def _replay_hold(
        self,
        *,
        account_id: UUID,
        idempotency_key: str,
    ) -> HoldResult | None:
        try:
            replay = await self._billing.lookup_idempotency(
                user_id=account_id,
                idempotency_key=idempotency_key,
            )
        except BillingValidationError as exc:
            if "another user" in str(exc).lower():
                raise CoinIdempotencyConflictError(
                    "Ключ идемпотентности уже использован другой учётной записью."
                ) from exc
            raise
        if replay is None:
            return None
        return self._hold_result_from_replay(account_id, replay)

    async def _replay_spend(
        self,
        *,
        account_id: UUID,
        idempotency_key: str,
        hold: CoinHold,
    ) -> SpendResult | None:
        try:
            replay = await self._billing.lookup_idempotency(
                user_id=account_id,
                idempotency_key=idempotency_key,
            )
        except BillingValidationError as exc:
            if "another user" in str(exc).lower():
                raise CoinIdempotencyConflictError(
                    "Ключ идемпотентности уже использован другой учётной записью."
                ) from exc
            raise
        if replay is None:
            return None
        body = replay.response_body
        step = int(body.get("step_amount", 0))
        refunded = int(body.get("refunded_amount", 0))
        return self._spend_result(
            hold,
            step=step,
            refunded=refunded,
            new_balance=int(replay.user.ai_coins),
            already_processed=True,
        )

    def _hold_result_from_replay(
        self,
        account_id: UUID,
        mutation: IdempotentCoinMutationResult,
    ) -> HoldResult:
        body = mutation.response_body
        raw_id = body.get("transaction_id") or body.get("hold_id")
        if not isinstance(raw_id, str) or not raw_id:
            raise CoinIdempotencyConflictError(
                "Ключ идемпотентности уже использован для другой операции."
            )
        remaining = int(body.get("remaining_amount", body.get("amount", 0)))
        captured = int(body.get("captured_amount", 0))
        return HoldResult(
            hold_id=UUID(raw_id),
            account_id=account_id,
            amount_held=int(body.get("amount", remaining + captured)),
            remaining_amount=remaining,
            captured_amount=captured,
            new_balance=int(mutation.user.ai_coins),
            status=str(body.get("status") or CoinHoldStatus.HELD.value),
            already_processed=True,
            idempotency_key=mutation.idempotency_key,
        )

    def _hold_result_from_row(
        self,
        hold: CoinHold,
        *,
        new_balance: int,
        already_processed: bool,
    ) -> HoldResult:
        return HoldResult(
            hold_id=hold.id,
            account_id=hold.user_id,
            amount_held=int(hold.amount),
            remaining_amount=int(hold.remaining_amount),
            captured_amount=int(hold.captured_amount),
            new_balance=new_balance,
            status=str(hold.status),
            already_processed=already_processed,
            idempotency_key=hold.idempotency_key,
        )

    def _spend_result(
        self,
        hold: CoinHold,
        *,
        step: int,
        refunded: int,
        new_balance: int,
        already_processed: bool,
    ) -> SpendResult:
        return SpendResult(
            hold_id=hold.id,
            account_id=hold.user_id,
            step_amount=step,
            remaining_amount=int(hold.remaining_amount),
            captured_amount=int(hold.captured_amount),
            refunded_amount=refunded,
            new_balance=new_balance,
            status=str(hold.status),
            already_processed=already_processed,
            generated_kept=True,
        )

    async def _append_audit(
        self,
        *,
        user_id: UUID,
        event_type: AuditEventType,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        await AuditLogRepository(self._session).record_event(
            AuditEventRecord(
                event_type=event_type,
                status=AuditEventStatus.SUCCESS,
                user_id=user_id,
                actor_type="system",
                message=message,
                metadata=metadata,
            ),
            commit=False,
        )

    async def _discard_unflushed_hold(self, hold: CoinHold) -> None:
        try:
            self._session.delete(hold)
            await self._session.flush()
        except Exception:
            logger.debug("Could not discard tentative coin hold", exc_info=True)

    async def _finish_write(self) -> None:
        if self._auto_commit:
            await self._session.commit()

    def _hold_ledger_body(self, hold: CoinHold) -> dict[str, Any]:
        return {
            "guard": "coin_guard",
            "hold_id": str(hold.id),
            "transaction_id": str(hold.id),
            "amount": int(hold.amount),
            "remaining_amount": int(hold.remaining_amount),
            "captured_amount": int(hold.captured_amount),
            "status": str(hold.status),
        }

    def _spend_ledger_body(
        self,
        hold: CoinHold,
        *,
        step: int,
        operation: str = "commit_spend",
    ) -> dict[str, Any]:
        return {
            "guard": "coin_guard",
            "hold_id": str(hold.id),
            "transaction_id": str(hold.id),
            "step_amount": int(step),
            "refunded_amount": int(step) if operation == "rollback_spend" else 0,
            "remaining_amount": int(hold.remaining_amount),
            "captured_amount": int(hold.captured_amount),
            "status": str(hold.status),
            "operation": operation,
        }
