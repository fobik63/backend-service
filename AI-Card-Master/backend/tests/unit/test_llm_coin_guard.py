"""Unit tests for LLM coin pre-debit guard, decorator, and batch stop."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.llm_coin_guard import LlmCoinGuard, require_llm_coins
from app.domain.llm_coin_guard import (
    BATCH_STOP_INSUFFICIENT,
    INSUFFICIENT_COINS_MESSAGE,
    PAYMENT_MODAL_HREF,
    PAYMENT_MODAL_ID,
    SEO_CARD_COST_COINS,
    InsufficientCoinsError,
    LlmCoinOperation,
    bind_idempotency_key,
)
from app.services.billing_service import BillingValidationError, IdempotentCoinMutationResult


class _WalletBilling:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user
        self.debits: list[int] = []
        self.refunds: list[int] = []

    async def debit_coins_in_transaction(self, *, user_id, amount, **_kwargs):
        if amount > int(self.user.ai_coins):
            raise BillingValidationError("Insufficient AI-coin balance.")
        self.user.ai_coins = int(self.user.ai_coins) - int(amount)
        self.debits.append(int(amount))
        return self.user

    async def refund_coins_in_transaction(self, *, user_id, amount, **_kwargs):
        self.user.ai_coins = int(self.user.ai_coins) + int(amount)
        self.refunds.append(int(amount))
        return self.user


class _Session:
    def __init__(self, user: SimpleNamespace) -> None:
        self._user = user

    async def get(self, _model, user_id):
        if str(user_id) == str(self._user.id):
            return self._user
        return None


class _DecoratedService:
    def __init__(self, guard: LlmCoinGuard) -> None:
        self._coin_guard = guard
        self.calls = 0

    @require_llm_coins(LlmCoinOperation.SEO_CARD)
    async def generate_via_llm(self, *, user_id, idempotency_key=None) -> str:
        self.calls += 1
        return "ok"


@pytest.mark.asyncio
async def test_predebit_then_call_charges_two_coins_for_seo_card() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=10)
    billing = _WalletBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)

    result, billed, amount = await guard.predebit_then_call(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        llm_call=_async_ok,
    )

    assert result == "ok"
    assert amount == SEO_CARD_COST_COINS
    assert billed is not None
    assert int(billed.ai_coins) == 8
    assert billing.debits == [2]


async def _async_ok() -> str:
    return "ok"


@pytest.mark.asyncio
async def test_insufficient_balance_raises_402_payload() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=1)
    billing = _WalletBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)

    with pytest.raises(InsufficientCoinsError) as exc_info:
        await guard.predebit_then_call(
            user_id=user_id,
            operation=LlmCoinOperation.SEO_CARD,
            llm_call=_async_ok,
        )

    detail = exc_info.value.to_http_detail()
    assert exc_info.value.status_code == 402
    assert detail["message"] == INSUFFICIENT_COINS_MESSAGE
    assert detail["payment_modal"] == PAYMENT_MODAL_ID
    assert detail["payment_modal_href"] == PAYMENT_MODAL_HREF
    assert detail["min_pack_coins"] == 50
    assert detail["required_coins"] == 2
    assert int(user.ai_coins) == 1
    assert billing.debits == []


@pytest.mark.asyncio
async def test_batch_stops_without_negative_and_keeps_generated() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=5)
    billing = _WalletBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)
    generated: list[str] = []

    async def generate_one(item: str) -> str:
        generated.append(item)
        return item.upper()

    persisted: list[int] = []

    async def persist() -> None:
        persisted.append(len(generated))

    batch = await guard.run_batch(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        items=["a", "b", "c", "d"],
        generate_one=generate_one,
        persist=persist,
    )

    assert batch.items == ("A", "B")
    assert batch.coins_charged == 4
    assert batch.skipped_count == 2
    assert batch.stopped_reason == BATCH_STOP_INSUFFICIENT
    assert int(user.ai_coins) == 1
    assert generated == ["a", "b"]
    assert persisted == [1, 2]


@pytest.mark.asyncio
async def test_llm_failure_refunds_predebit() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=6)
    billing = _WalletBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)

    async def boom() -> str:
        raise RuntimeError("llm down")

    with pytest.raises(RuntimeError):
        await guard.predebit_then_call(
            user_id=user_id,
            operation=LlmCoinOperation.REVIEW,
            llm_call=boom,
        )

    assert int(user.ai_coins) == 6
    assert billing.debits == [2]
    assert billing.refunds == [2]


@pytest.mark.asyncio
async def test_require_llm_coins_decorator_predebits() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=4)
    billing = _WalletBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)
    service = _DecoratedService(guard)

    assert await service.generate_via_llm(user_id=user_id) == "ok"
    assert service.calls == 1
    assert int(user.ai_coins) == 2


class _LedgerBilling:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user
        self.debits: list[int] = []
        self.ledger: dict[str, IdempotentCoinMutationResult] = {}

    async def debit_coins_idempotent_in_transaction(
        self,
        *,
        user_id,  # noqa: ANN001
        amount,
        idempotency_key=None,
        response_body=None,
        **_kwargs,
    ) -> IdempotentCoinMutationResult:
        if idempotency_key and idempotency_key in self.ledger:
            return self.ledger[idempotency_key]
        if amount > int(self.user.ai_coins):
            raise BillingValidationError("Insufficient AI-coin balance.")
        self.user.ai_coins = int(self.user.ai_coins) - int(amount)
        self.debits.append(int(amount))
        body = dict(response_body or {})
        result = IdempotentCoinMutationResult(
            user=self.user,
            already_processed=False,
            response_code=200,
            response_body=body,
            idempotency_key=idempotency_key,
        )
        if idempotency_key:
            self.ledger[idempotency_key] = IdempotentCoinMutationResult(
                user=self.user,
                already_processed=True,
                response_code=200,
                response_body=dict(body),
                idempotency_key=idempotency_key,
            )
        return result

    async def merge_idempotency_response_body(
        self,
        *,
        user_id,  # noqa: ANN001
        idempotency_key,
        extra,
    ) -> None:
        prior = self.ledger.get(idempotency_key)
        if prior is None:
            return
        body = dict(prior.response_body)
        body.update(dict(extra))
        self.ledger[idempotency_key] = IdempotentCoinMutationResult(
            user=self.user,
            already_processed=True,
            response_code=200,
            response_body=body,
            idempotency_key=idempotency_key,
        )


@pytest.mark.asyncio
async def test_ledger_replay_returns_cached_result_without_llm() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=10)
    billing = _LedgerBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)
    calls = {"n": 0}

    async def llm_call() -> dict[str, str]:
        calls["n"] += 1
        return {"text": "hello"}

    key = bind_idempotency_key(
        user_id=user_id,
        route="/api/ai/generate-description",
        body=b'{"title":"a"}',
    )
    first, _, first_amount = await guard.predebit_then_call(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        llm_call=llm_call,
        idempotency_key=key,
    )
    second, _, second_amount = await guard.predebit_then_call(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        llm_call=llm_call,
        idempotency_key=key,
    )

    assert first == {"text": "hello"}
    assert second == first
    assert first_amount == SEO_CARD_COST_COINS
    assert second_amount == 0
    assert calls["n"] == 1
    assert billing.debits == [2]
    assert int(user.ai_coins) == 8


@pytest.mark.asyncio
async def test_payload_change_binds_a_new_ledger_key_and_calls_llm() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=10)
    billing = _LedgerBilling(user)
    guard = LlmCoinGuard(_Session(user), billing=billing, charge_coins=True)
    calls = {"n": 0}

    async def llm_call() -> str:
        calls["n"] += 1
        return f"gen-{calls['n']}"

    key_a = bind_idempotency_key(
        user_id=user_id,
        route="/api/ai/generate-description",
        body=b'{"title":"a"}',
    )
    key_b = bind_idempotency_key(
        user_id=user_id,
        route="/api/ai/generate-description",
        body=b'{"title":"b"}',
    )
    assert key_a != key_b

    first, _, _ = await guard.predebit_then_call(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        llm_call=llm_call,
        idempotency_key=key_a,
    )
    second, _, _ = await guard.predebit_then_call(
        user_id=user_id,
        operation=LlmCoinOperation.SEO_CARD,
        llm_call=llm_call,
        idempotency_key=key_b,
    )

    assert first == "gen-1"
    assert second == "gen-2"
    assert calls["n"] == 2
    assert billing.debits == [2, 2]
