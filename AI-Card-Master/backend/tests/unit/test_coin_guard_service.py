"""Unit tests for CoinGuardService edge cases, holds, and HTTP error contracts."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.coin_guard_service import (
    BATCH_STOP_LLM_FAILURE,
    CoinGuardService,
    MemoryCoinSpendRateLimiter,
)
from app.core.pricing import CoinHoldStatus
from app.domain.coin_guard import (
    AccountBlockedError,
    AccountFrozenError,
    CoinAmountInvalidError,
    CoinHoldConflictError,
    CoinNotIntegerError,
    CoinOverflowError,
    CoinRateLimitError,
    InsufficientBalanceError,
    ZeroBalanceError,
    parse_positive_coin_amount,
)
from app.models.audit_log import AuditLog
from app.models.coin_hold import CoinHold
from app.models.user import User
from app.services.billing_service import (
    BillingValidationError,
    IdempotentCoinMutationResult,
)


def _settings(**overrides: object) -> SimpleNamespace:
    data = {
        "coin_guard_max_operation_coins": 1_000_000,
        "coin_guard_spend_per_minute": 30,
        "coin_guard_rate_window_seconds": 60,
        "audit_log_enabled": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class _FakeWallet:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user
        self.ledger: dict[str, IdempotentCoinMutationResult] = {}
        self.debits: list[int] = []
        self.refunds: list[int] = []

    async def lookup_idempotency(self, *, user_id, idempotency_key):  # noqa: ANN001
        hit = self.ledger.get(idempotency_key)
        if hit is None:
            return None
        if hit.user.id != user_id:
            raise BillingValidationError("Idempotency key belongs to another user.")
        return hit

    async def debit_coins_idempotent_in_transaction(
        self,
        *,
        user_id,  # noqa: ANN001
        amount: int,
        idempotency_key: str | None = None,
        response_body=None,  # noqa: ANN001
        response_code: int = 200,
        operation: str = "debit",
    ) -> IdempotentCoinMutationResult:
        if idempotency_key and idempotency_key in self.ledger:
            return self.ledger[idempotency_key]
        if amount < 0:
            raise BillingValidationError("Debit amount must be non-negative.")
        if amount > int(self.user.ai_coins):
            raise BillingValidationError("Insufficient AI-coin balance.")
        self.user.ai_coins = int(self.user.ai_coins) - int(amount)
        self.debits.append(int(amount))
        body = {
            "operation": operation,
            "amount": int(amount),
            "new_balance": int(self.user.ai_coins),
            **(dict(response_body) if response_body else {}),
        }
        result = IdempotentCoinMutationResult(
            user=self.user,
            already_processed=False,
            response_code=response_code,
            response_body=body,
            idempotency_key=idempotency_key,
        )
        if idempotency_key:
            self.ledger[idempotency_key] = IdempotentCoinMutationResult(
                user=self.user,
                already_processed=True,
                response_code=response_code,
                response_body=body,
                idempotency_key=idempotency_key,
            )
        return result

    async def refund_coins_in_transaction(
        self,
        *,
        user_id,  # noqa: ANN001
        amount: int,
        idempotency_key: str | None = None,
        response_body=None,  # noqa: ANN001
        response_code: int = 200,
    ) -> SimpleNamespace:
        if idempotency_key and idempotency_key in self.ledger:
            return self.ledger[idempotency_key].user
        self.user.ai_coins = int(self.user.ai_coins) + int(amount)
        self.refunds.append(int(amount))
        if idempotency_key:
            body = dict(response_body) if response_body else {}
            self.ledger[idempotency_key] = IdempotentCoinMutationResult(
                user=self.user,
                already_processed=True,
                response_code=response_code,
                response_body=body,
                idempotency_key=idempotency_key,
            )
        return self.user


class _FakeSession:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user
        self.holds: dict = {}
        self.added: list[object] = []
        self.committed = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, CoinHold):
            self.holds[obj.id] = obj

    def delete(self, obj: object) -> None:
        if isinstance(obj, CoinHold):
            self.holds.pop(obj.id, None)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, model, key, with_for_update=False):  # noqa: ANN001
        if model is User or model is SimpleNamespace:
            if str(key) == str(self.user.id):
                return self.user
            return None
        if model is CoinHold:
            return self.holds.get(key)
        return None

    async def scalar(self, _stmt):  # noqa: ANN001
        return None


def _service(
    user: SimpleNamespace,
    *,
    limiter: MemoryCoinSpendRateLimiter | None = None,
) -> tuple[CoinGuardService, _FakeWallet, _FakeSession]:
    session = _FakeSession(user)
    wallet = _FakeWallet(user)
    guard = CoinGuardService(
        session,  # type: ignore[arg-type]
        billing=wallet,  # type: ignore[arg-type]
        rate_limiter=limiter or MemoryCoinSpendRateLimiter(limit=100),
        settings=_settings(),
        auto_commit=False,
    )
    return guard, wallet, session


@pytest.mark.parametrize(
    "value",
    [0, -1, -99, 1.5, 2.0, Decimal("1.0"), "10", "1", True, False, b"2", None],
)
def test_parse_rejects_non_positive_integers(value: object) -> None:
    with pytest.raises((CoinAmountInvalidError, CoinNotIntegerError)):
        parse_positive_coin_amount(value)


def test_parse_rejects_overflow() -> None:
    with pytest.raises(CoinOverflowError) as exc:
        parse_positive_coin_amount(1_000_001)
    assert exc.value.status_code == 400
    assert exc.value.to_http_detail()["max_operation_coins"] == 1_000_000


def test_parse_accepts_strict_positive_int() -> None:
    assert parse_positive_coin_amount(1) == 1
    assert parse_positive_coin_amount(50) == 50


@pytest.mark.asyncio
async def test_zero_balance_is_402_with_missing_coins() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=0, is_banned=False, is_frozen=False
    )
    guard, _, _ = _service(user)
    with pytest.raises(ZeroBalanceError) as exc:
        await guard.validate_and_hold(
            account_id=user.id, amount=2, idempotency_key=uuid4()
        )
    body = exc.value.to_http_detail()
    assert exc.value.status_code == 402
    assert body["missing_coins"] == 2
    assert body["balance"] == 0
    assert user.ai_coins == 0


@pytest.mark.asyncio
async def test_insufficient_balance_reports_exact_deficit() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=3, is_banned=False, is_frozen=False
    )
    guard, _, _ = _service(user)
    with pytest.raises(InsufficientBalanceError) as exc:
        await guard.validate_and_hold(
            account_id=user.id, amount=5, idempotency_key=uuid4()
        )
    body = exc.value.to_http_detail()
    assert exc.value.status_code == 402
    assert body["required_coins"] == 5
    assert body["balance"] == 3
    assert body["missing_coins"] == 2
    assert user.ai_coins == 3


@pytest.mark.asyncio
async def test_banned_account_rejected_before_balance_check() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=0, is_banned=True, is_frozen=False
    )
    guard, _, _ = _service(user)
    with pytest.raises(AccountBlockedError) as exc:
        await guard.validate_and_hold(
            account_id=user.id, amount=1, idempotency_key=uuid4()
        )
    assert exc.value.status_code == 409
    assert user.ai_coins == 0


@pytest.mark.asyncio
async def test_frozen_account_rejected_before_balance_check() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=80, is_banned=False, is_frozen=True
    )
    guard, _, _ = _service(user)
    with pytest.raises(AccountFrozenError) as exc:
        await guard.validate_and_hold(
            account_id=user.id, amount=1, idempotency_key=uuid4()
        )
    assert exc.value.status_code == 409
    assert user.ai_coins == 80


@pytest.mark.asyncio
async def test_rate_limit_returns_429() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=50, is_banned=False, is_frozen=False
    )
    guard, _, _ = _service(user, limiter=MemoryCoinSpendRateLimiter(limit=1))
    await guard.validate_and_hold(
        account_id=user.id, amount=1, idempotency_key=uuid4()
    )
    with pytest.raises(CoinRateLimitError) as exc:
        await guard.validate_and_hold(
            account_id=user.id, amount=1, idempotency_key=uuid4()
        )
    assert exc.value.status_code == 429
    assert exc.value.to_http_detail()["retry_after_seconds"] == 60


@pytest.mark.asyncio
async def test_idempotent_hold_does_not_double_debit() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=10, is_banned=False, is_frozen=False
    )
    guard, wallet, _ = _service(user)
    key = uuid4()
    first = await guard.validate_and_hold(
        account_id=user.id, amount=4, idempotency_key=key
    )
    second = await guard.validate_and_hold(
        account_id=user.id, amount=4, idempotency_key=key
    )
    assert first.already_processed is False
    assert second.already_processed is True
    assert second.hold_id == first.hold_id
    assert user.ai_coins == 6
    assert wallet.debits == [4]


@pytest.mark.asyncio
async def test_hold_commit_and_partial_rollback_keeps_generated_spend() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=10, is_banned=False, is_frozen=False
    )
    guard, wallet, session = _service(user)
    hold = await guard.validate_and_hold(
        account_id=user.id,
        amount=2,
        units=3,
        unit_cost=2,
        idempotency_key=uuid4(),
    )
    assert hold.amount_held == 6
    assert user.ai_coins == 4
    captured = await guard.commit_spend(hold_id=hold.hold_id, amount=2)
    assert captured.captured_amount == 2
    assert captured.remaining_amount == 4
    assert user.ai_coins == 4
    rolled = await guard.rollback_spend(hold_id=hold.hold_id)
    assert rolled.refunded_amount == 4
    assert rolled.captured_amount == 2
    assert rolled.status == CoinHoldStatus.PARTIALLY_SETTLED.value
    assert rolled.generated_kept is True
    assert user.ai_coins == 8
    assert wallet.refunds == [4]
    assert any(isinstance(item, AuditLog) for item in session.added)
    assert int(user.ai_coins) >= 0


@pytest.mark.asyncio
async def test_commit_spend_rejects_step_larger_than_remaining() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=5, is_banned=False, is_frozen=False
    )
    guard, _, _ = _service(user)
    hold = await guard.validate_and_hold(
        account_id=user.id, amount=2, idempotency_key=uuid4()
    )
    with pytest.raises(CoinHoldConflictError) as exc:
        await guard.commit_spend(hold_id=hold.hold_id, amount=3)
    assert exc.value.status_code == 409
    assert user.ai_coins == 3


@pytest.mark.asyncio
async def test_batch_llm_failure_refunds_remaining_and_keeps_successes() -> None:
    user = SimpleNamespace(
        id=uuid4(), ai_coins=20, is_banned=False, is_frozen=False
    )
    guard, wallet, _ = _service(user)

    async def generate_one(item: int) -> int:
        if item == 2:
            raise RuntimeError("LLM timeout")
        return item * 10

    batch, items = await guard.run_batch(
        account_id=user.id,
        unit_cost=2,
        items=[0, 1, 2, 3, 4],
        generate_one=generate_one,
        idempotency_key=uuid4(),
    )
    assert items == (0, 10)
    assert batch.units_committed == 2
    assert batch.coins_captured == 4
    assert batch.coins_refunded == 6
    assert batch.stopped_reason == BATCH_STOP_LLM_FAILURE
    assert batch.status == CoinHoldStatus.PARTIALLY_SETTLED.value
    assert user.ai_coins == 16
    assert sum(wallet.refunds) == 6
    assert int(user.ai_coins) >= 0


@pytest.mark.asyncio
async def test_error_body_uses_russian_messages() -> None:
    err = ZeroBalanceError(
        "Нулевой баланс. Для операции требуется 2 коинов.",
        required_coins=2,
        balance=0,
        missing_coins=2,
    )
    body = err.to_error_body()
    assert body.status_code == 402
    assert "Нулевой баланс" in body.message
    assert body.missing_coins == 2
