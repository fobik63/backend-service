"""Unified YooKassa webhook ingress: Payment.find on every event + cancel lock."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.coin_billing_service import CoinBillingService
from app.application.payment_service import PaymentApplicationService
from app.application.yookassa_webhook_ingress import YooKassaWebhookIngress
from app.models.enums import PaymentStatus
from app.services.billing_service import BillingService


class _FindClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def find_payment(self, payment_id: str) -> dict[str, object]:
        self.calls.append(payment_id)
        return self.payload


@pytest.mark.asyncio
async def test_ingress_calls_find_for_canceled_event() -> None:
    client = _FindClient(
        {
            "id": "pay-1",
            "status": "canceled",
            "amount": {"value": "400.00", "currency": "RUB"},
        }
    )
    verified = await YooKassaWebhookIngress(client).verify(
        {"event": "payment.canceled", "object": {"id": "pay-1"}}
    )
    assert client.calls == ["pay-1"]
    assert verified.upstream_status == "canceled"
    assert verified.event == "payment.canceled"


@pytest.mark.asyncio
async def test_coin_cancel_does_not_apply_when_upstream_is_succeeded() -> None:
    yookassa = _FindClient(
        {
            "id": "pay-1",
            "status": "succeeded",
            "amount": {"value": "400.00", "currency": "RUB"},
        }
    )
    session = AsyncMock()
    service = CoinBillingService(session, yookassa=yookassa)  # type: ignore[arg-type]
    result = await service.process_yookassa_webhook(
        {"event": "payment.canceled", "object": {"id": "pay-1"}}
    )
    assert "cancel was not applied" in result.detail
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_tariff_cancel_calls_find_then_locked_mark() -> None:
    yookassa = _FindClient(
        {
            "id": "pay-tariff",
            "status": "canceled",
            "amount": {"value": "990.00", "currency": "RUB"},
        }
    )
    billing = AsyncMock()
    billing.mark_payment_canceled = AsyncMock(return_value=None)
    service = PaymentApplicationService(
        billing=billing,
        yookassa=yookassa,  # type: ignore[arg-type]
        winback=AsyncMock(),
        daily_bonus_coins=10,
    )
    result = await service.process_yookassa_webhook(
        {"event": "payment.canceled", "object": {"id": "pay-tariff"}}
    )
    assert result.detail == "Payment marked as canceled."
    assert yookassa.calls == ["pay-tariff"]
    billing.mark_payment_canceled.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_payment_canceled_uses_for_update() -> None:
    session = MagicMock()
    captured: dict[str, object] = {}

    async def _scalar(stmt: object) -> SimpleNamespace:
        captured["stmt"] = stmt
        return SimpleNamespace(
            status=PaymentStatus.SUCCEEDED,
            raw_webhook_payload=None,
        )

    session.scalar = _scalar
    billing = BillingService(session)
    payment = await billing.mark_payment_canceled(yookassa_payment_id="pay-1")
    assert payment is not None
    assert payment.status == PaymentStatus.SUCCEEDED
    stmt = captured["stmt"]
    assert getattr(stmt, "_for_update_arg", None) is not None
    session.commit.assert_not_called()
