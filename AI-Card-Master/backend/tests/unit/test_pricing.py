"""Unit tests for the operation pricing matrix and BillingService holds."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.pricing import (
    BillingService,
    CoinHoldStatus,
    PricingValidationError,
    ServiceType,
    calculate_cost,
    quote_cost,
)
from app.domain.generation import GenerationPostProcessingMode
from app.services.billing_service import BillingValidationError


def _settings(**overrides: object) -> SimpleNamespace:
    base = {
        "generation_charge_coins": True,
        "generation_fast_cost_coins": 1,
        "generation_hd_face_fix_cost_coins": 3,
        "brand_lora_training_cost_coins": 50,
        "three_d_gpu_rental_coins_per_minute": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_card_generation_preserves_default_base_prices() -> None:
    settings = _settings()
    assert (
        calculate_cost(ServiceType.CARD_GENERATION.value, "fast", {}, settings=settings)
        == 1
    )
    assert (
        calculate_cost(
            ServiceType.CARD_GENERATION.value, "hd_face_fix", {}, settings=settings
        )
        == 3
    )
    assert (
        calculate_cost(
            ServiceType.CARD_GENERATION.value,
            GenerationPostProcessingMode.FAST.value,
            {},
            settings=settings,
        )
        == 1
    )
    assert (
        calculate_cost(
            ServiceType.CARD_GENERATION.value,
            GenerationPostProcessingMode.HD_FACE_FIX.value,
            {},
            settings=settings,
        )
        == 3
    )


def test_three_d_mode_base_prices() -> None:
    settings = _settings()
    assert calculate_cost("three_d", "draft", {}, settings=settings) == 10
    assert calculate_cost("three_d", "standard", {}, settings=settings) == 30
    assert calculate_cost("three_d", "hd", {}, settings=settings) == 60


def test_three_d_polycount_texture_model_coefficients() -> None:
    settings = _settings()
    quote = quote_cost(
        "three_d",
        "standard",
        {
            "polycount_target": 250_000,
            "texture_resolution": 4096,
            "model": "premium",
        },
        settings=settings,
    )
    # 30 * 1.35 * 1.45 * 1.25 = 73.40625 → ceil 74
    assert quote.base_coins == 30
    assert quote.multiplier == Decimal("1.35") * Decimal("1.45") * Decimal("1.25")
    assert quote.total_coins == 74


def test_gpu_rental_matrix_rates() -> None:
    settings = _settings()
    assert (
        calculate_cost(
            "gpu_rental",
            "RTX_4090",
            {"minutes": 3, "gpu_type": "RTX_4090"},
            settings=settings,
        )
        == 6
    )
    assert (
        calculate_cost(
            "gpu_rental",
            "A100",
            {"minutes": 2, "gpu_type": "A100"},
            settings=settings,
        )
        == 10
    )


def test_charge_disabled_returns_zero() -> None:
    settings = _settings(generation_charge_coins=False)
    assert calculate_cost("three_d", "hd", {}, settings=settings) == 0
    assert calculate_cost("card_generation", "fast", {}, settings=settings) == 0


def test_unknown_service_raises() -> None:
    with pytest.raises(PricingValidationError):
        calculate_cost("unknown_svc", "fast", {}, settings=_settings())


@pytest.mark.asyncio
async def test_hold_commit_and_refund_flow() -> None:
    from app.models.coin_hold import CoinHold

    user_id = uuid4()
    holds: dict = {}
    balances = {user_id: 40}

    class _FakeWallet:
        def __init__(self, session: object) -> None:
            self._session = session

        async def lookup_idempotency(self, *, user_id, idempotency_key):
            return None

        async def debit_coins_idempotent_in_transaction(
            self,
            *,
            user_id,
            amount,
            idempotency_key=None,
            response_body=None,
            response_code=200,
            operation="debit",
        ):
            if balances[user_id] < amount:
                raise BillingValidationError("Insufficient AI-coin balance.")
            balances[user_id] -= amount
            user = SimpleNamespace(ai_coins=balances[user_id])
            body = {
                "operation": operation,
                "amount": amount,
                "new_balance": balances[user_id],
                **(dict(response_body) if response_body else {}),
            }
            from app.services.billing_service import IdempotentCoinMutationResult

            return IdempotentCoinMutationResult(
                user=user,
                already_processed=False,
                response_code=response_code,
                response_body=body,
                idempotency_key=idempotency_key,
            )

        async def debit_coins_in_transaction(self, *, user_id, amount):
            result = await self.debit_coins_idempotent_in_transaction(
                user_id=user_id, amount=amount
            )
            return result.user

        async def refund_coins_in_transaction(self, *, user_id, amount):
            balances[user_id] += amount
            return SimpleNamespace(ai_coins=balances[user_id])

    class _FakeSession:
        def add(self, obj: CoinHold) -> None:
            holds[obj.id] = obj

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def refresh(self, obj: CoinHold) -> None:
            return None

        async def get(self, model, key, with_for_update=False):  # noqa: ANN001
            assert model is CoinHold
            return holds.get(key)

    session = _FakeSession()
    billing = BillingService(session, settings=_settings())  # type: ignore[arg-type]
    billing._wallet = _FakeWallet(session)  # type: ignore[method-assign]

    tx_id = await billing.hold_coins(user_id, 30, service_type="three_d")
    assert balances[user_id] == 10
    assert holds[tx_id].status == CoinHoldStatus.HELD.value
    assert holds[tx_id].remaining_amount == 30
    assert holds[tx_id].captured_amount == 0

    status = await billing.commit_or_refund(tx_id, True)
    assert status is CoinHoldStatus.CAPTURED
    assert balances[user_id] == 10

    tx2 = await billing.hold_coins(user_id, 5, service_type="three_d")
    status2 = await billing.commit_or_refund(tx2, False)
    assert status2 is CoinHoldStatus.REFUNDED
    assert balances[user_id] == 10
