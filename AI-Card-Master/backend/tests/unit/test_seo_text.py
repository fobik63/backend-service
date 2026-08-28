"""Unit tests for OpenAI SEO text generation (service + parsing)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.application.seo_text_service import SEO_TEXT_COST_COINS, SeoTextService
from app.domain.llm_coin_guard import InsufficientCoinsError
from app.domain.seo_text import (
    SeoTargetPlatform,
    SeoTextConfigurationError,
    SeoTextContent,
    SeoTextGenerateRequest,
    SeoTextUpstreamError,
    SeoTokenUsage,
)
from app.infrastructure.openai.seo_text_client import (
    OpenAiSeoTextClient,
    resolve_openai_api_key,
)
from app.services.billing_service import BillingValidationError


def _request(**overrides: object) -> SeoTextGenerateRequest:
    payload = {
        "title": "Кроссовки беговые мужские",
        "category": "Обувь",
        "features": {"material": "mesh", "color": "black"},
        "target_platform": SeoTargetPlatform.WB,
    }
    payload.update(overrides)
    return SeoTextGenerateRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_seo_text_service_charges_one_coin_and_returns_usage() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=11)

    session = AsyncMock()
    session.commit = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()

    provider = MagicMock()
    provider.ensure_configured = MagicMock()
    provider.generate = AsyncMock(
        return_value=(
            SeoTextContent(
                optimized_title="Беговые кроссовки мужские легкие",
                benefits=(
                    "Легкая подошва",
                    "Дышащий верх",
                    "Амортизация",
                    "Надежная фиксация",
                ),
                description="A" * 900,
            ),
            SeoTokenUsage(
                prompt_tokens=100,
                completion_tokens=200,
                total_tokens=300,
            ),
        )
    )

    service = SeoTextService(
        session,
        provider=provider,
        billing=billing,
        charge_coins=True,
        cost_coins=SEO_TEXT_COST_COINS,
    )
    result = await service.generate(user_id=user_id, request=_request())

    billing.debit_coins_in_transaction.assert_awaited_once()
    assert billing.debit_coins_in_transaction.await_args.kwargs["amount"] == 2
    session.commit.assert_awaited_once()
    billing.refund_coins_in_transaction.assert_not_awaited()
    assert result.coins_charged == 2
    assert result.new_balance == 11
    assert result.usage.total_tokens == 300
    assert len(result.content.benefits) == 4


@pytest.mark.asyncio
async def test_seo_text_service_refunds_on_upstream_failure() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=4)

    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()

    provider = MagicMock()
    provider.ensure_configured = MagicMock()
    provider.generate = AsyncMock(side_effect=SeoTextUpstreamError("boom"))

    service = SeoTextService(
        session,
        provider=provider,
        billing=billing,
        charge_coins=True,
    )
    with pytest.raises(SeoTextUpstreamError):
        await service.generate(user_id=user_id, request=_request())

    billing.refund_coins_in_transaction.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_seo_text_service_insufficient_balance() -> None:
    user_id = uuid4()
    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(
        side_effect=BillingValidationError("Insufficient AI-coin balance.")
    )

    provider = MagicMock()
    provider.ensure_configured = MagicMock()

    service = SeoTextService(
        session,
        provider=provider,
        billing=billing,
        charge_coins=True,
    )
    with pytest.raises(InsufficientCoinsError):
        await service.generate(user_id=user_id, request=_request())
    provider.generate.assert_not_called()


def test_resolve_openai_api_key_prefers_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-llm")
    assert resolve_openai_api_key() == "sk-openai"


def test_resolve_openai_api_key_falls_back_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-llm")
    assert resolve_openai_api_key() == "sk-llm"


def test_resolve_openai_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(SeoTextConfigurationError):
        resolve_openai_api_key()


@pytest.mark.asyncio
async def test_openai_client_parses_response_and_truncates_wb() -> None:
    long_description = "X" * 2000
    body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "optimized_title": "SEO title product shoes",
                            "benefits": [
                                "Benefit one text",
                                "Benefit two text",
                                "Benefit three text",
                                "Benefit four text",
                                "Benefit five text",
                            ],
                            "description": long_description,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 80,
            "total_tokens": 130,
        },
    }
    response = httpx.Response(200, json=body, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    transport = httpx.MockTransport(lambda request: response)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.openai.com"
    ) as client:
        seo_client = OpenAiSeoTextClient(api_key="sk-test", http_client=client)
        with patch(
            "app.infrastructure.openai.seo_text_client.record_api_usage_cost",
            new_callable=AsyncMock,
        ) as record_cost:
            content, usage = await seo_client.generate(_request())

    assert usage.total_tokens == 130
    assert len(content.description) == 1200
    assert len(content.benefits) == 5
    record_cost.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_client_missing_key_raises_configuration_error() -> None:
    client = OpenAiSeoTextClient(api_key="")
    with pytest.raises(SeoTextConfigurationError):
        client.ensure_configured()
