"""Unit tests for Zero-Hallucination OCR ↔ description cross-check (plan §57)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.zero_hallucination_service import (
    ZeroHallucinationService,
    ZeroHallucinationValidationError,
)
from app.domain.smart_reasoning import ReasoningTaskKind, ReasoningTier, tier_for_task
from app.domain.zero_hallucination import (
    ANOMALY_RELIABILITY_CAP,
    VERDICT_LABEL_RU,
    ClaudeCrossCheckPayload,
    ContradictionItem,
    CrossCheckVerdict,
    OcrClaim,
    ZeroHallucinationCrossCheck,
    attach_reliability_to_advice,
    build_insufficient_cross_check,
    compute_advice_reliability_pct,
    finalize_cross_check,
    reliability_pct_from_confidence,
)


def _claim(
    claim_id: str = "c1",
    *,
    text: str = "Сталь 304",
    confidence: float = 0.9,
) -> OcrClaim:
    return OcrClaim(
        claim_id=claim_id,
        text=text,
        slide_index=0,
        claim_type="material",
        confidence=confidence,
    )


def _contradiction(
    *,
    severity: str = "hard",
    claim_id: str = "c1",
) -> ContradictionItem:
    return ContradictionItem(
        claim_id=claim_id,
        ocr_text="Сталь 304",
        description_evidence="Пластик ABS",
        severity=severity,  # type: ignore[arg-type]
        note="OCR говорит сталь, описание — пластик.",
    )


def test_zero_hallucination_routes_to_deep_opus() -> None:
    assert tier_for_task(ReasoningTaskKind.ZERO_HALLUCINATION) is ReasoningTier.SIMPLE


def test_hard_contradiction_marks_anomaly_and_caps_reliability() -> None:
    pct, verdict = compute_advice_reliability_pct(
        ocr_claim_count=3,
        hard_contradictions=1,
        soft_contradictions=0,
        description_chars=200,
        model_confidence=0.95,
    )
    assert verdict is CrossCheckVerdict.ANOMALY
    assert pct <= ANOMALY_RELIABILITY_CAP
    assert VERDICT_LABEL_RU[verdict] == "Аномалия"


def test_verified_when_no_contradictions() -> None:
    pct, verdict = compute_advice_reliability_pct(
        ocr_claim_count=3,
        hard_contradictions=0,
        soft_contradictions=0,
        description_chars=200,
        model_confidence=0.9,
    )
    assert verdict is CrossCheckVerdict.VERIFIED
    assert pct >= 80.0
    assert VERDICT_LABEL_RU[verdict] == "Проверено"


def test_two_soft_contradictions_are_anomaly() -> None:
    pct, verdict = compute_advice_reliability_pct(
        ocr_claim_count=4,
        hard_contradictions=0,
        soft_contradictions=2,
        description_chars=150,
        model_confidence=0.8,
    )
    assert verdict is CrossCheckVerdict.ANOMALY
    assert pct <= ANOMALY_RELIABILITY_CAP


def test_sparse_inputs_insufficient_data() -> None:
    pct, verdict = compute_advice_reliability_pct(
        ocr_claim_count=0,
        hard_contradictions=0,
        soft_contradictions=0,
        description_chars=5,
        model_confidence=0.5,
    )
    assert verdict is CrossCheckVerdict.INSUFFICIENT_DATA
    assert pct == 0.0
    assert VERDICT_LABEL_RU[verdict] == "Недостаточно данных"


def test_finalize_cross_check_applies_anomaly_label() -> None:
    payload = ClaudeCrossCheckPayload(
        ocr_claims=[_claim(), _claim("c2", text="Гарантия 2 года")],
        contradictions=[_contradiction(severity="hard")],
        supported_claim_ids=["c2"],
        model_confidence=0.88,
        reasoning_trace="OCR на слайде 1 противоречит описанию материала.",
    )
    result = finalize_cross_check(
        payload,
        description="Корпус из прочного пластика ABS. Гарантия 2 года.",
        model_name="claude-opus-4-7",
    )
    assert result.verdict is CrossCheckVerdict.ANOMALY
    assert result.verdict_label == "Аномалия"
    assert 0.0 <= result.advice_reliability_pct <= ANOMALY_RELIABILITY_CAP
    assert result.model_name == "claude-opus-4-7"
    assert len(result.contradictions) == 1


def test_finalize_verified_without_contradictions() -> None:
    payload = ClaudeCrossCheckPayload(
        ocr_claims=[_claim(), _claim("c2", text="IP67")],
        contradictions=[],
        supported_claim_ids=["c1", "c2"],
        model_confidence=0.92,
        reasoning_trace="OCR claims match description.",
    )
    result = finalize_cross_check(
        payload,
        description="Материал: сталь 304. Защита IP67. Для активного спорта.",
        model_name="claude-opus-4-7",
    )
    assert result.verdict is CrossCheckVerdict.VERIFIED
    assert result.verdict_label == "Проверено"
    assert result.advice_reliability_pct >= 80.0


def test_reliability_pct_from_confidence() -> None:
    assert reliability_pct_from_confidence(0.84) == 84.0
    assert reliability_pct_from_confidence(1.5) == 100.0
    assert reliability_pct_from_confidence(-0.1) == 0.0


def test_attach_reliability_caps_on_anomaly() -> None:
    cross = ZeroHallucinationCrossCheck(
        ocr_claims=[_claim()],
        contradictions=[_contradiction()],
        supported_claim_ids=[],
        verdict=CrossCheckVerdict.ANOMALY,
        verdict_label="Аномалия",
        advice_reliability_pct=40.0,
        model_confidence=0.7,
        reasoning_trace="conflict",
        model_name="claude-opus-4-7",
    )
    assert attach_reliability_to_advice(base_confidence=0.95, cross_check=cross) == 40.0


def test_insufficient_builder() -> None:
    result = build_insufficient_cross_check(reason="no images", model_name="x")
    assert result.verdict is CrossCheckVerdict.INSUFFICIENT_DATA
    assert result.advice_reliability_pct == 0.0
    assert result.verdict_label == "Недостаточно данных"


@pytest.mark.asyncio
async def test_service_returns_insufficient_without_images() -> None:
    checker = AsyncMock()
    checker.model_name = "claude-opus-4-7"
    service = ZeroHallucinationService(checker, enabled=True)
    result, in_tok, out_tok = await service.cross_check_card(
        images=(),
        title="Товар",
        description="Длинное описание товара для dual-check теста.",
        specs=["материал: сталь"],
        article="123",
    )
    assert result.verdict is CrossCheckVerdict.INSUFFICIENT_DATA
    assert result.advice_reliability_pct == 0.0
    assert in_tok == 0 and out_tok == 0
    checker.extract_and_cross_check.assert_not_called()


@pytest.mark.asyncio
async def test_service_runs_checker_and_finalizes_anomaly() -> None:
    checker = AsyncMock()
    checker.model_name = "claude-opus-4-7"
    checker.extract_and_cross_check = AsyncMock(
        return_value=(
            ClaudeCrossCheckPayload(
                ocr_claims=[_claim()],
                contradictions=[_contradiction(severity="hard")],
                supported_claim_ids=[],
                model_confidence=0.8,
                reasoning_trace="hard conflict on material",
            ),
            100,
            50,
        )
    )
    service = ZeroHallucinationService(checker, enabled=True)
    result, in_tok, out_tok = await service.cross_check_card(
        images=((b"fake-png", "image/png"),),
        title="Кружка",
        description="Корпус из пластика. Объём 300 мл. Для дома.",
        specs=["материал: пластик"],
        marketplace="wildberries",
        article="ART-1",
        user_id=uuid4(),
        job_id=uuid4(),
    )
    assert result.verdict is CrossCheckVerdict.ANOMALY
    assert result.verdict_label == "Аномалия"
    assert in_tok == 100 and out_tok == 50
    checker.extract_and_cross_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_disabled_skips_claude() -> None:
    checker = AsyncMock()
    checker.model_name = "claude-opus-4-7"
    service = ZeroHallucinationService(checker, enabled=False)
    result, _, _ = await service.cross_check_card(
        images=((b"x", "image/png"),),
        title="T",
        description="Описание достаточно длинное для проверки.",
        specs=[],
    )
    assert result.verdict is CrossCheckVerdict.INSUFFICIENT_DATA
    checker.extract_and_cross_check.assert_not_called()


def test_service_rejects_invalid_max_images() -> None:
    with pytest.raises(ZeroHallucinationValidationError):
        ZeroHallucinationService(None, max_vision_images=0)


def test_attach_cross_check_to_competitor_card() -> None:
    from app.domain.competitor_audit import (
        ActionableBlueprint,
        CompetitorCardDeepAnalysis,
        attach_cross_check_to_card,
    )

    card = CompetitorCardDeepAnalysis(
        article="A1",
        marketplace="wildberries",
        title="Test",
        competitor_weaknesses=[],
        conversion_triggers=["offer badge"],
        actionable_blueprint=ActionableBlueprint(
            background="white studio",
            pain_badges=["прочность"],
            generator_prompt="make better card",
            first_slide_offers=["-30%"],
            avoid_copying=[],
        ),
        confidence=0.9,
        reasoning_trace="ok",
    )
    cross = finalize_cross_check(
        ClaudeCrossCheckPayload(
            ocr_claims=[_claim(), _claim("c2", text="IP67")],
            contradictions=[],
            supported_claim_ids=["c1", "c2"],
            model_confidence=0.91,
            reasoning_trace="aligned",
        ),
        description="Сталь 304, защита IP67, для активного использования на улице.",
        model_name="claude-opus-4-7",
    )
    merged = attach_cross_check_to_card(card, cross_check=cross)
    assert merged.cross_check is not None
    assert merged.cross_check.verdict is CrossCheckVerdict.VERIFIED
    assert merged.advice_reliability_pct == cross.advice_reliability_pct


def test_advice_reliability_on_strategy_plan() -> None:
    from app.domain.ai_strategy import (
        StrategyActionType,
        RecommendationPriority,
        KillerRecommendation,
        StrategyCompareReport,
        StrategyCompareConfig,
        FeatureDelta,
        ClaudeStrategyEnrichment,
        build_plan_result,
    )

    compare = StrategyCompareReport(
        marketplace="wildberries",
        niche_key="cups",
        config=StrategyCompareConfig(),
        user_sku="U1",
        leader_sku="L1",
        user_ctr_pct=2.0,
        leader_ctr_pct=5.0,
        total_ctr_lift_pct=15.0,
        deltas=[
            FeatureDelta(
                action_type=StrategyActionType.REPLACE_BACKGROUND,
                step_order=1,
                feature_label="background",
                user_value="gray",
                leader_value="white studio",
                attributed_ctr_lift_pct=8.0,
                rationale="Конкурент использует это и имеет на 8% выше CTR",
                priority=RecommendationPriority.HIGH,
                gap_score=80.0,
            )
        ],
        recommendations=[
            KillerRecommendation(
                step_number=1,
                action_type=StrategyActionType.REPLACE_BACKGROUND,
                title="Заменить фон",
                instruction="Сделать белый студийный фон",
                rationale="Конкурент использует это и имеет на 8% выше CTR",
                attributed_ctr_lift_pct=8.0,
                priority=RecommendationPriority.HIGH,
                expected_impact="CTR +8%",
                advice_reliability_pct=80.0,
            )
        ],
    )
    enrichments = [
        ClaudeStrategyEnrichment(
            action_type=StrategyActionType.REPLACE_BACKGROUND,
            refined_title="Студийный фон как у лидера",
            instruction="Белый фон + мягкий свет",
            rationale="Конкурент использует это и имеет на 8% выше CTR",
            expected_impact="Рост CTR ≈8%",
            confidence=0.87,
        )
    ]
    plan = build_plan_result(
        compare_report=compare,
        enrichments=enrichments,
        model_name="claude-3-5-haiku",
    )
    assert plan.advice_reliability_pct == 87.0
    assert plan.recommendations[0].advice_reliability_pct == 87.0
