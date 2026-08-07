"""Unit tests for AI Token & Resource Governor + Semantic Filtering (plan §69)."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.token_governor_service import TokenResourceGovernor
from app.core.config import Settings
from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorReview,
    CompetitorSpecRow,
    build_competitor_deep_analysis_prompt,
)
from app.domain.semantic_filter import (
    build_card_snapshot,
    compute_competitor_context_delta,
    estimate_card_prompt_tokens,
    estimate_text_tokens,
)
from app.domain.smart_reasoning import (
    ReasoningTaskKind,
    ReasoningTier,
    model_for_task,
    tier_for_task,
)
from app.domain.token_governor import (
    GovernorAction,
    GovernorRequest,
    ProviderKind,
    TokenGovernorPolicy,
    decide_governor,
    is_local_eligible,
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "t" * 64,
        "CLAUDE_47_API_KEY": "claude-test-key",
        "TOKEN_GOVERNOR_ENABLED": True,
        "OLLAMA_ENABLED": True,
        "OLLAMA_MODEL": "llama3",
    }
    base.update(overrides)
    return Settings(**base)


def _card(**overrides: Any) -> CompetitorCardScrapeResult:
    payload: dict[str, Any] = {
        "source_url": "https://www.wildberries.ru/catalog/123/detail.aspx",
        "marketplace": CompetitorMarketplace.WILDBERRIES,
        "article": "123",
        "title": "Стул офисный",
        "description": "Описание " * 200,
        "specs": [
            CompetitorSpecRow(name="Материал", value="Пластик"),
            CompetitorSpecRow(name="Цвет", value="Чёрный"),
        ],
        "photo_urls": ["https://example.com/1.jpg"],
        "price_before_discount_kopecks": 500_000,
        "price_after_discount_kopecks": 399_000,
        "reviews_low": [
            CompetitorReview(rating=2, text=f"Хлипкий пластик номер {i}")
            for i in range(8)
        ],
        "reviews_high": [
            CompetitorReview(rating=5, text=f"Отличный стул {i}") for i in range(5)
        ],
    }
    payload.update(overrides)
    return CompetitorCardScrapeResult.model_validate(payload)


def test_local_tier_kinds() -> None:
    assert tier_for_task(ReasoningTaskKind.TEXT_CLASSIFICATION) is ReasoningTier.LOCAL
    assert tier_for_task(ReasoningTaskKind.SEMANTIC_COMPRESSION) is ReasoningTier.LOCAL
    assert (
        model_for_task(
            ReasoningTaskKind.TEXT_CLASSIFICATION,
            simple_model="haiku",
            deep_model="opus",
            local_model="llama3",
        )
        == "llama3"
    )


def test_is_local_eligible_blocks_vision() -> None:
    assert is_local_eligible(ReasoningTaskKind.PAIN_ANALYSIS) is True
    assert (
        is_local_eligible(ReasoningTaskKind.PAIN_ANALYSIS, has_vision=True) is False
    )
    assert is_local_eligible(ReasoningTaskKind.COMPETITOR_AUDIT) is False
    assert is_local_eligible(ReasoningTaskKind.EYE_OF_GOD) is False
    assert is_local_eligible(ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX) is True
    assert is_local_eligible(ReasoningTaskKind.ZERO_HALLUCINATION) is True


def test_governor_downgrades_competitor_without_vision() -> None:
    policy = TokenGovernorPolicy(
        enabled=True,
        ollama_enabled=False,
        always_semantic_filter_competitor=False,
    )
    decision = decide_governor(
        GovernorRequest(
            task_kind=ReasoningTaskKind.COMPETITOR_AUDIT,
            estimated_input_tokens=800,
            has_vision=False,
            semantic_filter_applied=True,
        ),
        policy=policy,
    )
    assert decision.action is GovernorAction.USE_CLAUDE
    assert decision.provider is ProviderKind.CLAUDE_SIMPLE
    assert decision.expected_cost_tier is ReasoningTier.SIMPLE


def test_governor_routes_routine_to_ollama() -> None:
    policy = TokenGovernorPolicy(enabled=True, ollama_enabled=True)
    decision = decide_governor(
        GovernorRequest(
            task_kind=ReasoningTaskKind.PAIN_ANALYSIS,
            estimated_input_tokens=800,
            has_vision=False,
        ),
        policy=policy,
    )
    assert decision.action is GovernorAction.USE_LOCAL
    assert decision.provider is ProviderKind.LOCAL_OLLAMA


def test_governor_keeps_competitor_on_claude_with_semantic_filter() -> None:
    policy = TokenGovernorPolicy(
        enabled=True,
        ollama_enabled=True,
        always_semantic_filter_competitor=True,
    )
    decision = decide_governor(
        GovernorRequest(
            task_kind=ReasoningTaskKind.COMPETITOR_AUDIT,
            estimated_input_tokens=12_000,
            has_vision=True,
            semantic_filter_applied=False,
        ),
        policy=policy,
    )
    assert decision.action is GovernorAction.COMPRESS_THEN_CLAUDE
    assert decision.apply_semantic_filter is True
    assert decision.provider is ProviderKind.CLAUDE_DEEP


def test_governor_rejects_over_hard_limit() -> None:
    policy = TokenGovernorPolicy(
        soft_input_token_limit=1000,
        hard_input_token_limit=2000,
        always_semantic_filter_competitor=False,
    )
    decision = decide_governor(
        GovernorRequest(
            task_kind=ReasoningTaskKind.ORACLE_ENRICHMENT,
            estimated_input_tokens=5000,
            semantic_filter_applied=True,
        ),
        policy=policy,
    )
    assert decision.action is GovernorAction.REJECT


def test_governor_cache_hit() -> None:
    gov = TokenResourceGovernor(policy=TokenGovernorPolicy())
    decision = gov.authorize(
        GovernorRequest(
            task_kind=ReasoningTaskKind.PAIN_ANALYSIS,
            cache_hit=True,
        )
    )
    assert decision.action is GovernorAction.USE_CACHE
    assert decision.provider is ProviderKind.CACHE


def test_baseline_semantic_filter_compresses() -> None:
    card = _card()
    before = estimate_card_prompt_tokens(card)
    delta = compute_competitor_context_delta(card, previous=None)
    assert delta.is_first_seen is True
    assert delta.estimated_tokens_after < before
    assert delta.compression_ratio < 1.0
    assert len(delta.new_reviews_low) <= 12


def test_temporal_delta_only_new_reviews() -> None:
    card = _card()
    snap = build_card_snapshot(card)
    updated = _card(
        reviews_low=list(card.reviews_low)
        + [CompetitorReview(rating=1, text="Новая боль: сломалась ножка")],
        price_after_discount_kopecks=350_000,
        description=card.description,
    )
    delta = compute_competitor_context_delta(updated, previous=snap)
    assert delta.is_first_seen is False
    assert delta.has_meaningful_changes is True
    assert any("Новая боль" in r for r in delta.new_reviews_low)
    assert any(c.kind.value == "price" for c in delta.changes)
    # Unchanged old reviews should not all be re-sent.
    assert len(delta.new_reviews_low) == 1


def test_delta_prompt_is_shorter_than_full_dump() -> None:
    card = _card()
    delta = compute_competitor_context_delta(card, previous=None)
    full = build_competitor_deep_analysis_prompt(card=card, image_count=1)
    compressed = build_competitor_deep_analysis_prompt(
        card=card,
        image_count=1,
        context_delta=delta,
    )
    assert "SEMANTIC_FILTER_DELTA" in compressed
    assert estimate_text_tokens(compressed) < estimate_text_tokens(full)


def test_settings_expose_governor_knobs() -> None:
    cfg = _settings(
        TOKEN_GOVERNOR_SOFT_INPUT_TOKENS=5000,
        OLLAMA_BASE_URL="http://ollama:11434",
    )
    assert cfg.token_governor_enabled is True
    assert cfg.token_governor_soft_input_tokens == 5000
    assert cfg.ollama_base_url == "http://ollama:11434"
    assert cfg.ollama_model == "llama3"


def test_text_task_classifier_keeps_small_pain_local() -> None:
    from app.domain.text_task_classifier import (
        TextTaskComplexity,
        classify_text_task_heuristic,
    )

    result = classify_text_task_heuristic(
        kind=ReasoningTaskKind.PAIN_ANALYSIS,
        text_blob="Хлипкий пластик. Плохие швы.",
        item_count=5,
        has_vision=False,
    )
    assert result.complexity is TextTaskComplexity.SIMPLE


def test_text_task_classifier_blocks_vision() -> None:
    from app.domain.text_task_classifier import (
        TextTaskComplexity,
        classify_text_task_heuristic,
        is_classifiable_text_task,
    )

    assert (
        is_classifiable_text_task(
            ReasoningTaskKind.PAIN_ANALYSIS,
            has_vision=True,
        )
        is False
    )
    result = classify_text_task_heuristic(
        kind=ReasoningTaskKind.COMPETITOR_AUDIT,
        text_blob="x" * 100,
        has_vision=True,
    )
    assert result.complexity is TextTaskComplexity.NEEDS_CLAUDE


def test_policy_hard_must_exceed_soft() -> None:
    with pytest.raises(ValueError):
        TokenGovernorPolicy(
            soft_input_token_limit=10_000,
            hard_input_token_limit=1000,
        )
