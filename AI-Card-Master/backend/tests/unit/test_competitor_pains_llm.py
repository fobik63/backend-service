"""Unit tests for competitor negative-review LLM pain analysis."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.competitor_pains_llm_service import CompetitorPainsLlmService
from app.domain.competitor_pains_llm import (
    COMPETITOR_PAINS_SYSTEM_PROMPT,
    CompetitorPainsAnalysisRequest,
    CompetitorPainsLlmProvider,
    CompetitorPainsUpstreamError,
    CompetitorPainsValidationError,
    build_competitor_pains_user_prompt,
    competitor_pains_system_prompt,
    normalize_competitor_pains_payload,
)
from app.infrastructure.competitor_pains_llm_factory import (
    resolve_competitor_pains_provider,
)


def _valid_payload() -> dict[str, Any]:
    return {
        "pains": [
            {
                "rank": 1,
                "title": "Жидкая текстура",
                "summary": "Крем растекается и плохо впитывается.",
                "evidence_quotes": ["слишком жидкий"],
            },
            {
                "rank": 2,
                "title": "Неприятный запах",
                "summary": "Покупатели жалуются на резкий аромат.",
                "evidence_quotes": ["плохо пахнет"],
            },
            {
                "rank": 3,
                "title": "Хрупкая крышка",
                "summary": "Упаковка ломается при открытии.",
                "evidence_quotes": ["сломана крышка"],
            },
        ],
        "recommendations": [
            {"pain_rank": 1, "offer_text": "Густая текстура — не течёт"},
            {"pain_rank": 2, "offer_text": "Нейтральный аромат без резкости"},
            {"pain_rank": 3, "offer_text": "Усиленная крышка, не ломается"},
        ],
    }


class _FakeLlm:
    def __init__(self, payload: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        self.payload = payload or _valid_payload()
        self.fail = fail
        self.calls: list[CompetitorPainsAnalysisRequest] = []
        self.closed = False

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return "gpt-test"

    def ensure_configured(self) -> None:
        return None

    async def analyze_negative_reviews(
        self,
        request: CompetitorPainsAnalysisRequest,
    ):
        self.calls.append(request)
        if self.fail:
            raise CompetitorPainsUpstreamError("boom")
        return normalize_competitor_pains_payload(
            self.payload,
            provider=CompetitorPainsLlmProvider.OPENAI,
            model_name=self.model_name,
            input_tokens=10,
            output_tokens=20,
        )

    async def aclose(self) -> None:
        self.closed = True


def test_system_prompt_matches_spec() -> None:
    assert "Ты аналитик маркетплейсов" in COMPETITOR_PAINS_SYSTEM_PROMPT
    assert "3 главные боли" in COMPETITOR_PAINS_SYSTEM_PROMPT
    assert "инфографики" in COMPETITOR_PAINS_SYSTEM_PROMPT
    assert "НАШЕЙ карточке" in COMPETITOR_PAINS_SYSTEM_PROMPT
    assert "JSON" in competitor_pains_system_prompt()


def test_request_dedupes_and_rejects_empty() -> None:
    req = CompetitorPainsAnalysisRequest(
        complaint_texts=["  жидкий  ", "Жидкий", "плохо пахнет", ""]
    )
    assert req.complaint_texts == ["жидкий", "плохо пахнет"]

    with pytest.raises(Exception):
        CompetitorPainsAnalysisRequest(complaint_texts=["  ", ""])


def test_normalize_accepts_alternate_keys() -> None:
    result = normalize_competitor_pains_payload(
        {
            "main_pains": ["A", "B", "C"],
            "infographic_offers": ["O1", "O2", "O3"],
        },
        provider=CompetitorPainsLlmProvider.OLLAMA,
        model_name="ollama:llama3",
    )
    assert len(result.pains) == 3
    assert result.pains[0].title == "A"
    assert result.recommendations[2].offer_text == "O3"
    assert result.provider is CompetitorPainsLlmProvider.OLLAMA


def test_user_prompt_includes_complaints() -> None:
    req = CompetitorPainsAnalysisRequest(
        complaint_texts=["жидкий", "плохо пахнет"],
        product_context="наш крем густой",
    )
    prompt = build_competitor_pains_user_prompt(req)
    assert "жидкий" in prompt
    assert "плохо пахнет" in prompt
    assert "наш крем густой" in prompt
    assert "pains" in prompt


@pytest.mark.asyncio
async def test_service_returns_structured_json() -> None:
    llm = _FakeLlm()
    service = CompetitorPainsLlmService(llm)
    result = await service.analyze_negative_reviews(
        CompetitorPainsAnalysisRequest(
            complaint_texts=["жидкий", "плохо пахнет", "сломана крышка"]
        )
    )
    assert len(result.pains) == 3
    assert len(result.recommendations) == 3
    assert result.recommendations[0].offer_text.startswith("Густая")
    assert len(llm.calls) == 1
    await service.aclose()
    assert llm.closed is True


@pytest.mark.asyncio
async def test_service_propagates_upstream_error() -> None:
    service = CompetitorPainsLlmService(_FakeLlm(fail=True))
    with pytest.raises(CompetitorPainsUpstreamError):
        await service.analyze_negative_reviews(
            CompetitorPainsAnalysisRequest(complaint_texts=["жидкий"])
        )


def test_resolve_provider_explicit_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITOR_PAINS_LLM_PROVIDER", "ollama")
    assert resolve_competitor_pains_provider() is CompetitorPainsLlmProvider.OLLAMA


def test_resolve_provider_explicit_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITOR_PAINS_LLM_PROVIDER", "openai")
    assert resolve_competitor_pains_provider() is CompetitorPainsLlmProvider.OPENAI


def test_service_rejects_empty_via_domain() -> None:
    with pytest.raises((CompetitorPainsValidationError, Exception)):
        CompetitorPainsAnalysisRequest(complaint_texts=[])
