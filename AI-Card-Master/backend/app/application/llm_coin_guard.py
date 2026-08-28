"""Pre-debit AI-coins before an LLM call; stepwise batch spend without negatives.

All balance mutations go through ``BillingService.debit_coins_in_transaction``
(single write-path / audit R1). The decorator / FastAPI dependency only
orchestrate cost calculation, the 402 gate, and per-unit capture.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, ParamSpec, TypeVar
from uuid import UUID

from app.domain.llm_coin_guard import (
    BATCH_STOP_INSUFFICIENT,
    InsufficientCoinsError,
    LlmCoinOperation,
    bind_idempotency_key,
    required_coins_for,
)
from app.models.user import User
from app.services.billing_service import (
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)

logger = logging.getLogger(__name__)

_LLM_RESULT_KEY = "llm_result"

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


def _user_balance(user: User) -> int:
    raw = getattr(user, "ai_coins", None)
    if raw is None:
        raw = getattr(user, "coins", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class BatchChargeResult(Generic[R]):
    """Partial-or-complete batch outcome after stepwise LLM coin capture."""

    items: tuple[R, ...]
    coins_charged: int
    new_balance: int
    skipped_count: int
    stopped_reason: str | None = None

    @property
    def interrupted(self) -> bool:
        return self.stopped_reason is not None


def _jsonable_llm_result(result: Any) -> Any:
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(result, tuple):
        return [_jsonable_llm_result(item) for item in result]
    return result


class LlmCoinGuard:
    """Check balance and pre-debit coins immediately before LLM generation."""

    def __init__(
        self,
        session: Any,
        *,
        billing: BillingService | None = None,
        charge_coins: bool = True,
    ) -> None:
        self._session = session
        self._billing = billing or BillingService(session)
        self._charge_coins = bool(charge_coins)

    @property
    def charge_coins(self) -> bool:
        return self._charge_coins

    def cost_for(self, operation: LlmCoinOperation, *, quantity: int = 1) -> int:
        if not self._charge_coins:
            return 0
        return required_coins_for(operation, quantity=quantity)

    async def peek_balance(self, user_id: UUID) -> int:
        user = await self._session.get(User, user_id)
        if user is None:
            raise BillingNotFoundError(f"User {user_id} not found.")
        return _user_balance(user)

    async def assert_can_afford_unit(
        self,
        *,
        user_id: UUID,
        operation: LlmCoinOperation,
        quantity: int = 1,
        balance_hint: int | None = None,
    ) -> int:
        """Fail-fast 402 when the wallet cannot cover even the first unit.

        Does not debit. Batch callers pass ``quantity=1`` so a 30-card job
        can still start when the user can pay for some, but not all, cards.
        """

        required = self.cost_for(operation, quantity=quantity)
        if required <= 0:
            if balance_hint is not None:
                return int(balance_hint)
            return await self.peek_balance(user_id)
        balance = (
            int(balance_hint)
            if balance_hint is not None
            else await self.peek_balance(user_id)
        )
        if balance < required:
            raise InsufficientCoinsError(required_coins=required, balance=balance)
        return balance

    async def debit(
        self,
        *,
        user_id: UUID,
        amount: int,
        idempotency_key: str | None = None,
        operation: LlmCoinOperation | str | None = None,
    ) -> User:
        """Atomically debit ``amount``; never leaves a negative balance."""

        user, _, _ = await self._debit_mutation(
            user_id=user_id,
            amount=amount,
            idempotency_key=idempotency_key,
            operation=operation,
        )
        return user

    async def _debit_mutation(
        self,
        *,
        user_id: UUID,
        amount: int,
        idempotency_key: str | None,
        operation: LlmCoinOperation | str | None,
    ) -> tuple[User, bool, dict[str, Any]]:
        if amount < 0:
            raise BillingValidationError("Debit amount must be non-negative.")
        if amount == 0 or not self._charge_coins:
            user = await self._session.get(User, user_id)
            if user is None:
                raise BillingNotFoundError(f"User {user_id} not found.")
            return user, False, {}

        body: dict[str, Any] = {"guard": "llm_coin_predebit"}
        if operation is not None:
            body["llm_operation"] = str(operation)
        try:
            idempotent = getattr(
                type(self._billing),
                "debit_coins_idempotent_in_transaction",
                None,
            )
            if inspect.iscoroutinefunction(idempotent):
                mutation = await self._billing.debit_coins_idempotent_in_transaction(
                    user_id=user_id,
                    amount=amount,
                    idempotency_key=idempotency_key,
                    response_body=body,
                )
                extra = (
                    mutation.response_body
                    if isinstance(mutation.response_body, dict)
                    else {}
                )
                return (
                    mutation.user,
                    bool(mutation.already_processed),
                    dict(extra),
                )
            user = await self._billing.debit_coins_in_transaction(
                user_id=user_id,
                amount=amount,
                idempotency_key=idempotency_key,
                response_body=body,
            )
            return user, False, {}
        except BillingValidationError as exc:
            if "insufficient" in str(exc).lower():
                balance = 0
                try:
                    balance = await self.peek_balance(user_id)
                except BillingNotFoundError:
                    pass
                raise InsufficientCoinsError(
                    required_coins=amount,
                    balance=balance,
                ) from exc
            raise

    async def _store_llm_result(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        result: Any,
    ) -> None:
        if not idempotency_key:
            return
        merge = getattr(type(self._billing), "merge_idempotency_response_body", None)
        if not inspect.iscoroutinefunction(merge):
            return
        await self._billing.merge_idempotency_response_body(
            user_id=user_id,
            idempotency_key=idempotency_key,
            extra={_LLM_RESULT_KEY: _jsonable_llm_result(result)},
        )

    async def refund(self, *, user_id: UUID, amount: int) -> None:
        if amount <= 0 or not self._charge_coins:
            return
        try:
            await self._billing.refund_coins_in_transaction(
                user_id=user_id,
                amount=amount,
            )
        except Exception:
            logger.exception(
                "Failed to refund LLM coins for user_id=%s amount=%s",
                user_id,
                amount,
            )

    async def predebit_then_call(
        self,
        *,
        user_id: UUID,
        operation: LlmCoinOperation,
        llm_call: Callable[[], Awaitable[R]],
        quantity: int = 1,
        idempotency_key: str | None = None,
    ) -> tuple[R, User | None, int]:
        """Debit the full cost, run ``llm_call``, refund the debit on failure."""

        amount = self.cost_for(operation, quantity=quantity)
        user, already_processed, ledger_body = await self._debit_mutation(
            user_id=user_id,
            amount=amount,
            idempotency_key=idempotency_key,
            operation=operation,
        )
        if already_processed:
            cached = ledger_body.get(_LLM_RESULT_KEY)
            if cached is not None:
                return cached, user, 0
        try:
            result = await llm_call()
        except Exception:
            if not already_processed:
                await self.refund(user_id=user_id, amount=amount)
            raise
        await self._store_llm_result(
            user_id=user_id,
            idempotency_key=idempotency_key,
            result=result,
        )
        return result, user, 0 if already_processed else amount

    async def run_batch(
        self,
        *,
        user_id: UUID,
        operation: LlmCoinOperation,
        items: Sequence[T],
        generate_one: Callable[[T], Awaitable[R]],
        persist: Callable[[], Awaitable[None]] | None = None,
        idempotency_key: str | None = None,
    ) -> BatchChargeResult[R]:
        """Debit one unit at a time. Stop when the wallet cannot cover the next.

        Already generated items stay persisted via ``persist`` (typically
        ``session.commit``). The first unit that cannot be paid raises 402
        when nothing has been produced yet.
        """

        unit = self.cost_for(operation, quantity=1)
        produced: list[R] = []
        charged = 0
        stopped_reason: str | None = None
        last_user: User | None = None

        for index, item in enumerate(items):
            step_key: str | None = None
            dump_json = getattr(item, "model_dump_json", None)
            if callable(dump_json):
                step_key = bind_idempotency_key(
                    user_id=user_id,
                    route=f"{operation}:batch:{index}",
                    body=dump_json(),
                )
            elif idempotency_key:
                step_key = f"{idempotency_key}:llm-batch:{index}"
            try:
                last_user, already_processed, ledger_body = await self._debit_mutation(
                    user_id=user_id,
                    amount=unit,
                    idempotency_key=step_key,
                    operation=operation,
                )
            except InsufficientCoinsError:
                if produced:
                    stopped_reason = BATCH_STOP_INSUFFICIENT
                    break
                raise
            if already_processed:
                cached = ledger_body.get(_LLM_RESULT_KEY)
                if cached is not None:
                    produced.append(cached)
                    continue
            try:
                generated = await generate_one(item)
            except Exception:
                if not already_processed:
                    await self.refund(user_id=user_id, amount=unit)
                raise
            await self._store_llm_result(
                user_id=user_id,
                idempotency_key=step_key,
                result=generated,
            )
            if persist is not None:
                await persist()
            produced.append(generated)
            charged += 0 if already_processed else unit

        if last_user is not None:
            new_balance = _user_balance(last_user)
        else:
            new_balance = await self.peek_balance(user_id)

        return BatchChargeResult(
            items=tuple(produced),
            coins_charged=charged,
            new_balance=new_balance,
            skipped_count=max(0, len(items) - len(produced)),
            stopped_reason=stopped_reason,
        )


def require_llm_coins(
    operation: LlmCoinOperation,
    *,
    quantity: int = 1,
    guard_attr: str = "_coin_guard",
    user_id_arg: str = "user_id",
    idempotency_key_arg: str = "idempotency_key",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Async decorator: pre-debit ``quantity`` units, refund if the call fails.

    The wrapped method must expose ``self.<guard_attr>`` (an ``LlmCoinGuard``)
    and accept ``user_id`` (UUID). Optional ``idempotency_key`` is forwarded
    to the billing ledger.
    """

    if quantity < 1:
        raise ValueError("quantity must be >= 1.")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("require_llm_coins only wraps async callables.")

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = inspect.signature(func).bind(*args, **kwargs)
            bound.apply_defaults()
            self = bound.arguments.get("self")
            if self is None:
                raise TypeError("require_llm_coins requires a bound method with self.")
            guard = getattr(self, guard_attr, None)
            if not isinstance(guard, LlmCoinGuard):
                raise TypeError(
                    f"{type(self).__name__}.{guard_attr} must be an LlmCoinGuard."
                )
            user_id = bound.arguments.get(user_id_arg)
            if user_id is None:
                raise TypeError(f"Missing {user_id_arg} for LLM coin pre-debit.")
            idempotency_key = bound.arguments.get(idempotency_key_arg)
            result, _, _ = await guard.predebit_then_call(
                user_id=user_id,
                operation=operation,
                quantity=quantity,
                idempotency_key=idempotency_key if isinstance(idempotency_key, str) else None,
                llm_call=lambda: func(*args, **kwargs),
            )
            return result

        return wrapper

    return decorator
