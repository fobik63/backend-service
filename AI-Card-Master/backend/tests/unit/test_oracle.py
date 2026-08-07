"""Unit tests for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.oracle_service import (
    OracleNotFoundError,
    OracleService,
    OracleValidationError,
)
from app.domain.oracle import (
    ClaudeGapEnrichment,
    GapSeverity,
    OracleEnqueueRequest,
    OracleGapConfig,
    OracleJobStatus,
    OracleJobView,
    SearchQuerySignal,
    SupplyCardSignal,
    build_niche_notification,
    build_prediction_result,
    compute_gap_score,
    compute_growth_ratio,
    detect_market_gaps,
)


def _query(**kwargs) -> SearchQuerySignal:
    base = {
        "query_text": "инфографика минимализм",
        "design_style": "минимализм",
        "niche_key": "home-decor",
        "baseline_volume": 1000,
        "recent_volume": 1800,
    }
    base.update(kwargs)
    return SearchQuerySignal.model_validate(base)


def _card(**kwargs) -> SupplyCardSignal:
    base = {
        "sku": "SKU-1",
        "rank": 5,
        "design_style": "минимализм",
        "niche_key": "home-decor",
        "review_count": 120,
    }
    base.update(kwargs)
    return SupplyCardSignal.model_validate(base)


def test_niche_notification_format() -> None:
    msg = build_niche_notification("Luxury Loft")
    assert msg == (
        "Обнаружена ниша! Сделай инфографику в стиле Luxury Loft, "
        "чтобы забрать трафик"
    )


def test_growth_ratio_and_gap_score() -> None:
    assert compute_growth_ratio(baseline_volume=1000, recent_volume=1500) == 0.5
    score = compute_gap_score(
        growth_ratio=0.5,
        recent_volume=2000,
        top_card_count=1,
        config=OracleGapConfig(),
    )
    assert 40.0 <= score <= 100.0


def test_detects_niche_when_demand_rises_and_top_cards_scarce() -> None:
    report = detect_market_gaps(
        marketplace="wildberries",
        niche_key="home-decor",
        search_queries=[
            _query(
                query_text="постер минимализм",
                design_style="минимализм",
                baseline_volume=800,
                recent_volume=1600,
            ),
            _query(
                query_text="карточка минимализм wb",
                design_style="минимализм",
                baseline_volume=400,
                recent_volume=900,
            ),
        ],
        supply_cards=[
            _card(sku="A", rank=3, design_style="минимализм"),
            _card(sku="B", rank=12, design_style="минимализм"),
        ],
        config=OracleGapConfig(
            min_query_growth_ratio=0.25,
            min_recent_query_volume=500,
            max_top_cards_for_gap=3,
            min_gap_score=40.0,
        ),
    )
    assert len(report.opportunities) == 1
    gap = report.opportunities[0]
    assert gap.design_style == "минимализм"
    assert gap.top_card_count == 2
    assert gap.growth_ratio > 0.25
    assert "Обнаружена ниша!" in gap.notification_message
    assert "минимализм" in gap.notification_message
    assert gap.severity in {
        GapSeverity.LOW,
        GapSeverity.MEDIUM,
        GapSeverity.HIGH,
        GapSeverity.CRITICAL,
    }


def test_no_gap_when_top_supply_is_saturated() -> None:
    cards = [
        _card(sku=f"S{i}", rank=i + 1, design_style="минимализм")
        for i in range(8)
    ]
    report = detect_market_gaps(
        marketplace="ozon",
        niche_key="home-decor",
        search_queries=[
            _query(baseline_volume=500, recent_volume=2000),
        ],
        supply_cards=cards,
        config=OracleGapConfig(max_top_cards_for_gap=3),
    )
    assert report.opportunities == []


def test_no_gap_when_demand_is_flat() -> None:
    report = detect_market_gaps(
        marketplace="wildberries",
        niche_key="home-decor",
        search_queries=[
            _query(baseline_volume=1000, recent_volume=1050),  # +5%
        ],
        supply_cards=[],
        config=OracleGapConfig(min_query_growth_ratio=0.25),
    )
    assert report.opportunities == []


def test_prediction_result_prefers_claude_notification() -> None:
    report = detect_market_gaps(
        marketplace="wildberries",
        niche_key="home-decor",
        search_queries=[_query(baseline_volume=500, recent_volume=1500)],
        supply_cards=[_card(rank=4)],
    )
    assert report.opportunities
    style = report.opportunities[0].design_style
    enrichment = ClaudeGapEnrichment(
        design_style=style,
        refined_style_label="Soft Minimal",
        notification_message=(
            "Обнаружена ниша! Сделай инфографику в стиле Soft Minimal, "
            "чтобы забрать трафик"
        ),
        infographic_brief="Чистый фон, крупный оффер, контрастный акцент.",
        traffic_capture_tips=["Первый слайд — боль покупателя"],
        confidence=0.91,
        reasoning_trace="Demand up, supply thin.",
    )
    result = build_prediction_result(
        scan_report=report,
        enrichments=[enrichment],
        model_name="claude-opus-4-7",
    )
    assert result.notifications[0].startswith("Обнаружена ниша!")
    assert "Soft Minimal" in result.notifications[0]
    assert result.confidence_score == pytest.approx(0.91)


class _FakeOracleRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, OracleJobView] = {}

    async def create_job(self, **kwargs) -> OracleJobView:
        job_id = uuid4()
        now = datetime.now(UTC)
        view = OracleJobView(
            id=job_id,
            user_id=kwargs["user_id"],
            status=OracleJobStatus.QUEUED,
            celery_task_id=None,
            niche_key=kwargs["niche_key"],
            marketplace=kwargs["marketplace"],
            queries_payload=tuple(kwargs["queries_payload"]),
            supply_payload=tuple(kwargs["supply_payload"]),
            gap_config=kwargs["gap_config"],
            scan_report=None,
            prediction_result=None,
            notifications=None,
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

    async def find_idempotent_job(self, **kwargs) -> OracleJobView | None:
        return None

    async def get_job_for_user(self, *, user_id: UUID, job_id: UUID) -> OracleJobView | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id: UUID) -> OracleJobView | None:
        return self.jobs.get(job_id)

    async def list_recent_notifications(self, *, user_id: UUID, limit: int = 20):
        items = [
            j
            for j in self.jobs.values()
            if j.user_id == user_id and j.notifications
        ]
        return items[:limit]

    async def mark_status(self, *, job_id: UUID, status: OracleJobStatus, **kwargs):
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

    async def save_scan_report(self, *, job_id: UUID, scan_report: dict):
        job = self.jobs[job_id]
        updated = replace(job, scan_report=scan_report, updated_at=datetime.now(UTC))
        self.jobs[job_id] = updated
        return updated

    async def save_scan_checkpoint(
        self,
        *,
        job_id: UUID,
        scan_report: dict,
        next_status: OracleJobStatus,
    ):
        job = self.jobs[job_id]
        updated = replace(
            job,
            scan_report=scan_report,
            status=next_status,
            updated_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        prediction_result: dict,
        notifications: list[str],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ):
        job = self.jobs[job_id]
        updated = replace(
            job,
            prediction_result=prediction_result,
            notifications=notifications,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            status=OracleJobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated


@pytest.mark.asyncio
async def test_service_run_emits_deterministic_notifications_without_claude() -> None:
    repo = _FakeOracleRepo()
    service = OracleService(
        repo,
        model_name="claude-opus-4-7",
        redis_stage_ttl_seconds=60,
        enrichment=None,
    )
    user_id = uuid4()
    request = OracleEnqueueRequest(
        niche_key="home-decor",
        marketplace="Wildberries",
        search_queries=[_query(baseline_volume=600, recent_volume=1800)],
        supply_cards=[_card(rank=2)],
    )
    job, replay = await service.enqueue_prediction(user_id=user_id, request=request)
    assert replay is False
    finished = await service.run_oracle_prediction(job_id=job.id)
    assert finished.status == OracleJobStatus.COMPLETED
    assert finished.notifications
    assert finished.notifications[0].startswith("Обнаружена ниша!")
    assert finished.prediction_result is not None


@pytest.mark.asyncio
async def test_service_get_job_not_found() -> None:
    service = OracleService(
        _FakeOracleRepo(),
        model_name="claude-opus-4-7",
        redis_stage_ttl_seconds=60,
    )
    with pytest.raises(OracleNotFoundError):
        await service.get_job_for_user(user_id=uuid4(), job_id=uuid4())


def test_service_rejects_empty_model_name() -> None:
    with pytest.raises(OracleValidationError):
        OracleService(_FakeOracleRepo(), model_name="  ", redis_stage_ttl_seconds=60)
