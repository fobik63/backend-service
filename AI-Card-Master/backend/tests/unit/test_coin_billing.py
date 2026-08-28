"""Unit tests for AI-coin volume pricing, YooKassa IP allowlist, and SDK adapter."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.core.yookassa_webhook_ips import (
    YOOKASSA_TARIFF_WEBHOOK_PATH,
    YOOKASSA_WEBHOOK_PATH,
    YOOKASSA_WEBHOOK_PATHS,
    is_allowed_yookassa_webhook_request,
    is_yookassa_notification_ip,
)
from app.domain.coin_pricing import (
    MAX_PURCHASE_COINS,
    MIN_PURCHASE_COINS,
    CoinPricingError,
    list_coin_packages,
    quote_coin_purchase,
    unit_price_rub_for_coins,
)
from app.infrastructure.yookassa_sdk_client import YooKassaSdkClient
from app.schemas.billing import CreateCoinPaymentRequest


def test_minimum_purchase_is_fifty_coins() -> None:
    with pytest.raises(CoinPricingError, match="50"):
        quote_coin_purchase(49)


def test_preset_packs_have_decreasing_unit_price() -> None:
    packs = list_coin_packages()
    assert [p.amount_coins for p in packs] == [50, 250, 1000, 5000]
    unit_prices = [p.unit_price_rub for p in packs]
    assert unit_prices == sorted(unit_prices, reverse=True)
    assert packs[0].amount_rub == Decimal("400.00")
    assert packs[-1].amount_rub == Decimal("19500.00")


def test_custom_amount_uses_matching_volume_tier() -> None:
    quote = quote_coin_purchase(80)
    assert quote.package_code == "custom"
    assert quote.unit_price_rub == unit_price_rub_for_coins(50)
    assert quote.amount_rub == Decimal("640.00")
    larger = quote_coin_purchase(1200)
    assert larger.unit_price_rub == unit_price_rub_for_coins(1000)
    assert larger.unit_price_rub < quote.unit_price_rub


def test_create_payment_schema_rejects_below_minimum() -> None:
    with pytest.raises(ValidationError):
        CreateCoinPaymentRequest(user_id=uuid4(), amount_coins=MIN_PURCHASE_COINS - 1)


def test_create_payment_schema_rejects_above_maximum() -> None:
    with pytest.raises(ValidationError):
        CreateCoinPaymentRequest(user_id=uuid4(), amount_coins=MAX_PURCHASE_COINS + 1)


def test_quote_rejects_above_maximum() -> None:
    with pytest.raises(CoinPricingError, match="5000"):
        quote_coin_purchase(MAX_PURCHASE_COINS + 1)


def test_yookassa_notification_ip_allowlist() -> None:
    assert is_yookassa_notification_ip("185.71.76.1")
    assert is_yookassa_notification_ip("77.75.156.11")
    assert is_yookassa_notification_ip("2a02:5180::1")
    assert not is_yookassa_notification_ip("8.8.8.8")
    assert not is_yookassa_notification_ip("not-an-ip")


def _request(client_host: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/billing/webhook/yookassa",
            "raw_path": b"/api/v1/billing/webhook/yookassa",
            "query_string": b"",
            "headers": [],
            "client": (client_host, 443),
            "server": ("test", 443),
        }
    )


def test_webhook_ip_enforcement_rejects_unknown_peers() -> None:
    with patch(
        "app.core.yookassa_webhook_ips.get_settings",
        return_value=SimpleNamespace(
            yookassa_webhook_ip_enforcement=True,
            cloudflare_trust_headers=False,
            trusted_proxy_cidrs="",
            app_env="development",
        ),
    ):
        assert is_allowed_yookassa_webhook_request(_request("185.71.76.10"))
        assert not is_allowed_yookassa_webhook_request(_request("1.2.3.4"))


def test_webhook_ip_enforcement_forced_in_production() -> None:
    with patch(
        "app.core.yookassa_webhook_ips.get_settings",
        return_value=SimpleNamespace(
            yookassa_webhook_ip_enforcement=False,
            cloudflare_trust_headers=False,
            trusted_proxy_cidrs="",
            app_env="production",
        ),
    ):
        assert is_allowed_yookassa_webhook_request(_request("185.71.76.10"))
        assert not is_allowed_yookassa_webhook_request(_request("1.2.3.4"))


def test_both_yookassa_webhook_paths_are_allowlisted() -> None:
    assert YOOKASSA_WEBHOOK_PATH in YOOKASSA_WEBHOOK_PATHS
    assert YOOKASSA_TARIFF_WEBHOOK_PATH in YOOKASSA_WEBHOOK_PATHS


@pytest.mark.asyncio
async def test_sdk_client_calls_payment_create_and_find() -> None:
    settings = SimpleNamespace(
        yookassa_shop_id="shop-1",
        yookassa_secret_key=SimpleNamespace(get_secret_value=lambda: "secret"),
        yookassa_vat_code=1,
    )
    quote = quote_coin_purchase(50)
    user_id = uuid4()
    created_payload = {
        "id": "pay-abc",
        "status": "pending",
        "amount": {"value": "400.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "confirmation_url": "https://yk.test/c"},
        "description": quote.description[:128],
        "metadata": {"user_id": str(user_id)},
    }
    found_payload = {**created_payload, "status": "succeeded"}

    create_obj = MagicMock()
    create_obj.json.return_value = created_payload
    find_obj = MagicMock()
    find_obj.json.return_value = found_payload

    with (
        patch(
            "app.infrastructure.yookassa_sdk_client.YooKassaSdkPayment.create",
            return_value=create_obj,
        ) as create_mock,
        patch(
            "app.infrastructure.yookassa_sdk_client.YooKassaSdkPayment.find_one",
            return_value=find_obj,
        ) as find_mock,
        patch(
            "app.infrastructure.yookassa_sdk_client.Configuration"
        ),
    ):
        client = YooKassaSdkClient(settings=settings)  # type: ignore[arg-type]
        created = await client.create_coin_payment(
            quote=quote,
            user_id=user_id,
            customer_email="seller@example.com",
            idempotency_key="idem-1",
            return_url="https://app.test/return",
        )
        found = await client.find_payment("pay-abc")

    assert created.payment_id == "pay-abc"
    assert created.confirmation_url == "https://yk.test/c"
    assert found["status"] == "succeeded"
    create_kwargs = create_mock.call_args
    params = create_kwargs.args[0]
    assert params["confirmation"]["type"] == "redirect"
    assert params["confirmation"]["return_url"] == "https://app.test/return"
    assert "receipt" in params
    assert params["receipt"]["items"][0]["payment_mode"] == "full_payment"
    find_mock.assert_called_once_with("pay-abc")


def test_billing_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/billing/create-payment" in paths
    assert "post" in paths["/api/v1/billing/create-payment"]
    assert "/api/v1/billing/webhook/yookassa" in paths
    assert "post" in paths["/api/v1/billing/webhook/yookassa"]
    assert "/api/v1/billing/coin-packs" in paths


@pytest.mark.asyncio
async def test_webhook_handler_rejects_non_allowlisted_ip() -> None:
    from app.api.dependencies.yookassa_webhook import require_yookassa_webhook_source

    with patch(
        "app.api.dependencies.yookassa_webhook.is_allowed_yookassa_webhook_request",
        return_value=False,
    ):
        with pytest.raises(HTTPException) as exc:
            await require_yookassa_webhook_source(_request("1.2.3.4"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_webhook_handler_acks_unknown_payment() -> None:
    from unittest.mock import AsyncMock

    from app.api.billing import yookassa_webhook
    from app.schemas.billing import YooKassaWebhookAckResponse
    from app.services.billing_service import BillingNotFoundError

    billing = AsyncMock()
    billing.process_yookassa_webhook.side_effect = BillingNotFoundError("missing")
    result = await yookassa_webhook(
        request=_request("185.71.76.10"),
        payload={"event": "payment.succeeded", "object": {"id": "pay-missing"}},
        billing=billing,
    )
    assert isinstance(result, YooKassaWebhookAckResponse)
    assert result.success is True
    assert result.detail == "Webhook accepted."
