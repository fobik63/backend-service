"""Unit tests for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.ai_strategy_service import (
    StrategyNotFoundError,
    StrategyService,
    StrategyValidationError,
)
from app.domain.ai_strategy import (
    ClaudeStrategyEnrichment,
    StrategyActionType,
    StrategyCardSnapshot,
    StrategyCompareConfig,
    StrategyEnqueueRequest,
    StrategyJobStatus,
    StrategyJobView,
    build_ctr_rationale,
    build_plan_result,
    compare_user_vs_leader,
    compute_ctr_lift_pct,
)


def _card(**kwargs) -> StrategyCardSnapshot:
    base = {
        "sku": "USER-1",
        "title": "Крем для лица 50 мл",
        "niche_key": "beauty-cream",
        "background_style": "белый студийный",
        "first_slide_pain_hook": "сухая кожа",
        "infographic_structure": "3 иконки",
        "contrast_accents": "голубой",
        "offer_text": "увлажнение 24ч",
        "price_badge": None,
        "ctr_pct": 2.0,
        "review_count": 80,
        "rank": 40,
    }
    base.update(kwargs)
    return StrategyCardSnapshot.model_validate(base)


def _leader(**kwargs) -> StrategyCardSnapshot:
    base = {
        "sku": "LEADER-1",
        "title": "Крем-хит: увлажнение + SPF",
        "niche_key": "beauty-cream",
        "background_style": "lifestyle loft",
        "first_slide_pain_hook": "морщины до 30",
        "infographic_structure": "до/после + 5 выгод",
        "contrast_accents": "красный акцент",
        "offer_text": "-30% сегодня",
        "price_badge": "хит продаж",
        "ctr_pct": 2.3,  # ~15% lift vs 2.0
        "review_count": 420,
        "rank": 3,
    }
    base.update(kwargs)
    return StrategyCardSnapshot.model_validate(base)


def test_ctr_rationale_format() -> None:
    msg = build_ctr_rationale(feature_label="фон", ctr_lift_pct=15.2)
    assert msg == "Конкурент использует фон и имеет на 15% выше CTR"


def test_ctr_lift_pct() -> None:
    assert compute_ctr_lift_pct(user_ctr_pct=2.0, leader_ctr_pct=2.3) == pytest.approx(
        15.0
    )


def test_compare_builds_ordered_plan_from_background_to_title() -> None:
    report = compare_user_vs_leader(
        marketplace="Wildberries",
        niche_key="beauty-cream",
        user_card=_card(),
        leader_card=_leader(),
        config=StrategyCompareConfig(min_ctr_lift_pct=5.0),
    )
    assert report.recommendations
    assert report.total_ctr_lift_pct == pytest.approx(15.0)
    actions = [r.action_type for r in report.recommendations]
    assert actions[0] == StrategyActionType.REPLACE_BACKGROUND
    assert StrategyActionType.CHANGE_TITLE in actions
    # Order must follow ACTION_STEP_ORDER
    order_index = {
        StrategyActionType.REPLACE_BACKGROUND: 0,
        StrategyActionType.RESTRUCTURE_FIRST_SLIDE: 1,
        StrategyActionType.ADD_INFOGRAPHIC: 2,
        StrategyActionType.ADJUST_CONTRAST_ACCENTS: 3,
        StrategyActionType.REWRITE_OFFER: 4,
        StrategyActionType.UPDATE_PRICE_BADGE: 5,
        StrategyActionType.CHANGE_TITLE: 6,
    }
    indices = [order_index[a] for a in actions]
    assert indices == sorted(indices)
    for rec in report.recommendations:
        assert "выше CTR" in rec.rationale
        assert "Конкурент использует" in rec.rationale


def test_no_plan_when_leader_ctr_not_advantageous() -> None:
    report = compare_user_vs_leader(
        marketplace="ozon",
        niche_key="beauty-cream",
        user_card=_card(ctr_pct=3.0),
        leader_card=_leader(ctr_pct=3.05),
        config=StrategyCompareConfig(
            min_ctr_lift_pct=10.0,
            min_absolute_ctr_gap=0.5,
            require_leader_ctr_advantage=True,
        ),
    )
    assert report.recommendations == []


def test_identical_features_yield_empty_plan() -> None:
    twin = _card(sku="LEADER-X", ctr_pct=3.0)
    report = compare_user_vs_leader(
        marketplace="wildberries",
        niche_key="beauty-cream",
        user_card=_card(ctr_pct=2.0),
        leader_card=twin,
    )
    assert report.recommendations == []
    assert any("дельта" in n.lower() or "совпадают" in n.lower() for n in report.compare_notes)


def test_plan_result_prefers_claude_instruction_keeps_ctr_rationale() -> None:
    report = compare_user_vs_leader(
        marketplace="wildberries",
        niche_key="beauty-cream",
        user_card=_card(),
        leader_card=_leader(),
    )
    assert report.recommendations
    first = report.recommendations[0]
    enrichment = ClaudeStrategyEnrichment(
        action_type=first.action_type,
        refined_title="Сменить фон на lifestyle",
        instruction="Поставь тёплый loft-фон как у лидера.",
        rationale="без CTR",  # should be replaced by deterministic
        expected_impact="Рост CTR в выдаче.",
        confidence=0.88,
    )
    result = build_plan_result(
        compare_report=report,
        enrichments=[enrichment],
        model_name="claude-opus-4-7",
        executive_summary="Killer plan ready.",
    )
    matched = next(
        r for r in result.recommendations if r.action_type == first.action_type
    )
    assert matched.title == "Сменить фон на lifestyle"
    assert "выше CTR" in matched.rationale
    assert result.executive_summary == "Killer plan ready."
    assert result.confidence_score == pytest.approx(0.88)


def test_enqueue_request_rejects_same_sku() -> None:
    with pytest.raises(Exception):
        StrategyEnqueueRequest(
            niche_key="beauty-cream",
            marketplace="wb",
            user_card=_card(sku="SAME"),
            leader_card=_leader(sku="SAME"),
        )


class _FakeStrategyRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, StrategyJobView] = {}

    async def create_job(self, **kwargs) -> StrategyJobView:
        job_id = uuid4()
        now = datetime.now(UTC)
        view = StrategyJobView(
            id=job_id,
            user_id=kwargs["user_id"],
            status=StrategyJobStatus.QUEUED,
            celery_task_id=None,
            niche_key=kwargs["niche_key"],
            marketplace=kwargs["marketplace"],
            user_card_payload=kwargs["user_card_payload"],
            leader_card_payload=kwargs["leader_card_payload"],
            compare_config=kwargs["compare_config"],
            compare_report=None,
            plan_result=None,
            model_name=kwargs["model_name"],
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[job_id] = view
        return view

    async def find_idempotent_job(self, **kwargs) -> StrategyJobView | None:
        return None

    async def get_job_for_user(self, *, user_id: UUID, job_id: UUID) -> StrategyJobView | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id: UUID) -> StrategyJobView | None:
        return self.jobs.get(job_id)

    async def mark_status(self, *, job_id: UUID, status: StrategyJobStatus, **kwargs):
        job = self.jobs[job_id]
        updated = replace(
            job,
            status=status,
            celery_task_id=kwargs.get("celery_task_id", job.celery_task_id),
            error_message=kwargs.get("error_message", job.error_message),
            completed_at=kwargs.get("completed_at", job.completed_at),
            updated_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated

    async def save_compare_report(self, *, job_id: UUID, compare_report: dict):
        job = self.jobs[job_id]
        updated = replace(
            job, compare_report=compare_report, updated_at=datetime.now(UTC)
        )
        self.jobs[job_id] = updated
        return updated

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        plan_result: dict,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ):
        job = self.jobs[job_id]
        updated = replace(
            job,
            plan_result=plan_result,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            status=StrategyJobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated


@pytest.mark.asyncio
async def test_service_run_emits_deterministic_plan_without_claude() -> None:
    repo = _FakeStrategyRepo()
    service = StrategyService(
        repo,
        model_name="claude-opus-4-7",
        redis_stage_ttl_seconds=60,
        planning=None,
    )
    user_id = uuid4()
    request = StrategyEnqueueRequest(
        niche_key="beauty-cream",
        marketplace="Wildberries",
        user_card=_card(),
        leader_card=_leader(),
    )
    job, replay = await service.enqueue_plan(user_id=user_id, request=request)
    assert replay is False
    finished = await service.run_strategy_plan(job_id=job.id)
    assert finished.status == StrategyJobStatus.COMPLETED
    assert finished.plan_result is not None
    recs = finished.plan_result["recommendations"]
    assert len(recs) >= 1
    assert "выше CTR" in recs[0]["rationale"]


@pytest.mark.asyncio
async def test_service_get_job_not_found() -> None:
    service = StrategyService(
        _FakeStrategyRepo(),
        model_name="claude-opus-4-7",
        redis_stage_ttl_seconds=60,
    )
    with pytest.raises(StrategyNotFoundError):
        await service.get_job_for_user(user_id=uuid4(), job_id=uuid4())


def test_service_rejects_empty_model_name() -> None:
    with pytest.raises(StrategyValidationError):
        StrategyService(_FakeStrategyRepo(), model_name="  ", redis_stage_ttl_seconds=60)
