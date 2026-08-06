"""Edge-case stability scenarios for external API integrations.

Covers Midjourney / Claude / YooKassa (and marketplace sellers): timeouts,
retries, malformed payloads, and typed upstream errors so the API process
never crashes when a third-party stalls.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from anthropic import APITimeoutError
from httpx import Response
from PIL import Image

from app.core.config import Settings
from app.domain.export import MarketplaceSellerError
from app.infrastructure.claude.client import Claude47VisionClient, ClaudeUpstreamError
from app.infrastructure.http_resilience import call_with_transport_retry
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient
from app.services.ai_engine import (
    AIEngineUpstreamError,
    MidjourneyConfig,
    MidjourneyService,
)
from app.services.yookassa_service import (
    YooKassaService,
    YooKassaUpstreamError,
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "t" * 64,
        "YOOKASSA_SHOP_ID": "test-shop",
        "YOOKASSA_SECRET_KEY": "test-secret",
        "YOOKASSA_API_BASE_URL": "https://api.yookassa.test/v3",
        "YOOKASSA_RETURN_URL": "https://app.test/return",
        "YOOKASSA_TIMEOUT_SECONDS": 2.0,
        "YOOKASSA_MAX_RETRIES": 2,
        "YOOKASSA_BASE_RETRY_DELAY_SECONDS": 0.01,
        "CLAUDE_47_API_KEY": "claude-test-key",
        "CLAUDE_47_MAX_RETRIES": 2,
        "CLAUDE_47_BASE_RETRY_DELAY_SECONDS": 0.01,
    }
    base.update(overrides)
    return Settings(**base)


def _product_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 40, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Shared retry helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_retry_exhausts_then_raises() -> None:
    calls = {"n": 0}

    async def boom() -> str:
        calls["n"] += 1
        raise httpx.ConnectTimeout("upstream down")

    with pytest.raises(httpx.ConnectTimeout):
        await call_with_transport_retry(
            boom,
            max_retries=2,
            base_delay_seconds=0.01,
            operation_name="unit-test",
        )
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_transport_retry_recovers_after_timeout() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow peer")
        return "ok"

    result = await call_with_transport_retry(
        flaky,
        max_retries=2,
        base_delay_seconds=0.01,
        operation_name="unit-test-recover",
    )
    assert result == "ok"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Midjourney
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_midjourney_timeout_maps_to_upstream_error() -> None:
    respx.post("https://provider.test/jobs/imagine").mock(
        side_effect=httpx.ReadTimeout("Midjourney stalled")
    )
    service = MidjourneyService(
        MidjourneyConfig(
            api_key="provider-key",
            base_url="https://provider.test",
            name="primary",
            webhook_token="webhook-secret",
            max_retries=1,
            base_retry_delay_seconds=0.01,
        )
    )
    try:
        with pytest.raises(AIEngineUpstreamError, match="temporarily unavailable"):
            await service.submit(
                product_image=_product_png(),
                selected_style="studio",
                prompt="clean premium background",
                reply_url="https://api.test/webhook?token=secret",
                reply_ref="signed.reply.reference",
            )
    finally:
        await service.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_midjourney_retries_then_succeeds_on_503() -> None:
    route = respx.post("https://provider.test/jobs/imagine").mock(
        side_effect=[
            Response(503, text="busy"),
            Response(201, json={"jobid": "job-recovered", "status": "created"}),
        ]
    )
    service = MidjourneyService(
        MidjourneyConfig(
            api_key="provider-key",
            base_url="https://provider.test",
            name="primary",
            webhook_token="webhook-secret",
            max_retries=2,
            base_retry_delay_seconds=0.01,
        )
    )
    try:
        submission = await service.submit(
            product_image=_product_png(),
            selected_style="studio",
            prompt="clean premium background",
            reply_url="https://api.test/webhook?token=secret",
            reply_ref="signed.reply.reference",
        )
    finally:
        await service.aclose()

    assert submission.external_job_id == "job-recovered"
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# YooKassa
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_yookassa_timeout_becomes_upstream_error() -> None:
    respx.post("https://api.yookassa.test/v3/payments").mock(
        side_effect=httpx.ReadTimeout("YooKassa stalled")
    )
    service = YooKassaService(_settings())

    with pytest.raises(YooKassaUpstreamError, match="failed after retries"):
        await service.create_tariff_payment(
            user_id="11111111-1111-1111-1111-111111111111",
            tariff_code="start",
        )


@pytest.mark.asyncio
@respx.mock
async def test_yookassa_retries_on_502_then_succeeds() -> None:
    route = respx.post("https://api.yookassa.test/v3/payments").mock(
        side_effect=[
            Response(502, text="bad gateway"),
            Response(
                200,
                json={
                    "id": "yk-payment-1",
                    "status": "pending",
                    "amount": {"value": "990.00", "currency": "RUB"},
                    "confirmation": {
                        "type": "redirect",
                        "confirmation_url": "https://yookassa.test/confirm",
                    },
                    "description": "test",
                    "metadata": {"user_id": "u1", "tariff_code": "start"},
                },
            ),
        ]
    )
    service = YooKassaService(_settings())
    created = await service.create_tariff_payment(
        user_id="11111111-1111-1111-1111-111111111111",
        tariff_code="start",
        idempotence_key="idem-1",
    )

    assert created.payment_id == "yk-payment-1"
    assert created.amount_rub == Decimal("990.00")
    assert created.confirmation_url == "https://yookassa.test/confirm"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_yookassa_malformed_json_is_upstream_error() -> None:
    respx.post("https://api.yookassa.test/v3/payments").mock(
        return_value=Response(200, text="not-json{{{")
    )
    service = YooKassaService(_settings())

    with pytest.raises(YooKassaUpstreamError, match="non-JSON"):
        await service.create_tariff_payment(
            user_id="11111111-1111-1111-1111-111111111111",
            tariff_code="start",
        )


@pytest.mark.asyncio
@respx.mock
async def test_yookassa_get_payment_timeout_is_upstream_error() -> None:
    respx.get("https://api.yookassa.test/v3/payments/pay-1").mock(
        side_effect=httpx.ConnectError("DNS failed")
    )
    service = YooKassaService(_settings())

    with pytest.raises(YooKassaUpstreamError, match="failed after retries"):
        await service.get_payment("pay-1")


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_sdk_timeout_retries_then_upstream_error() -> None:
    settings = _settings()
    client = Claude47VisionClient(settings)
    client._sdk = MagicMock()
    client._sdk.messages = MagicMock()
    client._sdk.messages.parse = AsyncMock(
        side_effect=APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))
    )
    client._retry_delay = lambda attempt, response: 0.0  # type: ignore[method-assign]

    try:
        with pytest.raises(ClaudeUpstreamError, match="failed after retries"):
            await client._messages_parse(
                system="sys",
                content=[{"type": "text", "text": "hi"}],
                output_format=MagicMock,
                max_tokens=100,
                operation="unit_test",
                user_id=None,
                job_id=None,
                fallback_schema={"type": "object"},
            )
        assert client._sdk.messages.parse.await_count == settings.claude_47_max_retries + 1
    finally:
        with patch.object(client._sdk, "close", new=AsyncMock()):
            await client.aclose()


@pytest.mark.asyncio
async def test_claude_sdk_recovers_after_timeout() -> None:
    settings = _settings()
    client = Claude47VisionClient(settings)

    parsed = MagicMock()
    ok_response = MagicMock()
    ok_response.parsed_output = parsed
    ok_response.usage = MagicMock(input_tokens=10, output_tokens=5)

    client._sdk = MagicMock()
    client._sdk.messages = MagicMock()
    client._sdk.messages.parse = AsyncMock(
        side_effect=[
            APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")),
            ok_response,
        ]
    )
    client._retry_delay = lambda attempt, response: 0.0  # type: ignore[method-assign]
    client._record_usage = AsyncMock()  # type: ignore[method-assign]

    class _Out:
        @classmethod
        def model_validate(cls, data: Any) -> Any:
            return data

    try:
        result, in_tok, out_tok = await client._messages_parse(
            system="sys",
            content=[{"type": "text", "text": "hi"}],
            output_format=_Out,
            max_tokens=100,
            operation="unit_test",
            user_id=None,
            job_id=None,
            fallback_schema={"type": "object"},
        )
        assert result is parsed
        assert in_tok == 10
        assert out_tok == 5
        assert client._sdk.messages.parse.await_count == 2
    finally:
        with patch.object(client._sdk, "close", new=AsyncMock()):
            await client.aclose()


# ---------------------------------------------------------------------------
# Marketplace sellers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_wildberries_timeout_maps_to_seller_error() -> None:
    respx.post("https://content-api.wildberries.ru/content/v2/cards/upload").mock(
        side_effect=httpx.ReadTimeout("WB stalled")
    )
    client = WildberriesSellerClient(timeout_seconds=1.0)

    with pytest.raises(MarketplaceSellerError, match="timed out|unreachable"):
        await client.create_product_draft(
            credentials={"api_token": "token"},
            vendor_code="SKU-1",
            title="Кроссовки мужские беговые летние",
            description="x" * 200,
            characteristics=("Лёгкие", "Дышащие"),
            image_urls=("https://cdn.test/a.jpg",),
            extras={"subject_id": 123},
        )


@pytest.mark.asyncio
@respx.mock
async def test_wildberries_non_json_body_maps_to_seller_error() -> None:
    respx.post("https://content-api.wildberries.ru/content/v2/cards/upload").mock(
        return_value=Response(200, text="<html>oops</html>")
    )
    client = WildberriesSellerClient(timeout_seconds=1.0)

    with pytest.raises(MarketplaceSellerError, match="non-JSON"):
        await client.create_product_draft(
            credentials={"api_token": "token"},
            vendor_code="SKU-1",
            title="Кроссовки мужские беговые летние",
            description="x" * 200,
            characteristics=("Лёгкие", "Дышащие"),
            image_urls=("https://cdn.test/a.jpg",),
            extras={"subject_id": 123},
        )
