"""Unit tests for AI Cost Dashboard & Resource Analytics (plan §80)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.cost_analytics_schemas import snapshot_to_response
from app.application.cost_analytics_service import CostAnalyticsService, normalize_cost_event
from app.domain.cost_analytics import (
    CostAlertKind,
    CostAlertPolicy,
    CostCallStatus,
    CostEventRecord,
    PeriodCostTotals,
    TokenPricing,
    build_provider_breakdown,
    calculate_token_cost,
    compute_profitability,
    empty_period_totals,
    evaluate_cost_alerts,
    is_generation_operation,
    quantize_usd,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.events: list[CostEventRecord] = []
        self.today = PeriodCostTotals(
            cost_usd=Decimal("12.500000"),
            events_count=5,
            success_count=4,
            error_count=1,
            timeout_count=0,
            generation_events_count=2,
            generation_cost_usd=Decimal("4.000000"),
            total_input_tokens=1000,
            total_output_tokens=500,
            total_duration_ms=4000,
            duration_samples=4,
        )
        self.week = PeriodCostTotals(
            cost_usd=Decimal("40.000000"),
            events_count=20,
            success_count=18,
            error_count=2,
            timeout_count=0,
            generation_events_count=8,
            generation_cost_usd=Decimal("16.000000"),
            total_input_tokens=8000,
            total_output_tokens=2000,
            total_duration_ms=16000,
            duration_samples=16,
        )
        self.month = PeriodCostTotals(
            cost_usd=Decimal("120.000000"),
            events_count=60,
            success_count=55,
            error_count=4,
            timeout_count=1,
            generation_events_count=24,
            generation_cost_usd=Decimal("48.000000"),
            total_input_tokens=24000,
            total_output_tokens=6000,
            total_duration_ms=48000,
            duration_samples=48,
        )
        self.baseline = PeriodCostTotals(
            cost_usd=Decimal("20.000000"),
            events_count=14,
            success_count=14,
            error_count=0,
            timeout_count=0,
            generation_events_count=10,
            generation_cost_usd=Decimal("10.000000"),
            total_input_tokens=5000,
            total_output_tokens=1000,
            total_duration_ms=7000,
            duration_samples=14,
        )
        self.providers = {
            "anthropic": (Decimal("80.000000"), 40),
            "midjourney": (Decimal("40.000000"), 20),
        }

    async def record_event(self, event: CostEventRecord, *, commit: bool = True) -> None:
        _ = commit
        self.events.append(event)

    async def sum_rollups(self, *, day_from: date, day_to: date) -> PeriodCostTotals:
        span = (day_to - day_from).days
        if span == 0:
            return self.today
        if span <= 6:
            # baseline window is 7 days ending yesterday → distinguish via day_to
            today = datetime.now(UTC).date()
            if day_to < today:
                return self.baseline
            return self.week
        return self.month

    async def sum_rollups_by_provider(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> dict[str, tuple[Decimal, int]]:
        _ = day_from, day_to
        return self.providers

    async def list_most_expensive(self, *, since: datetime, limit: int = 10):
        _ = since
        from app.domain.cost_analytics import ExpensiveOperation

        return [
            ExpensiveOperation(
                id=str(uuid4()),
                provider="anthropic",
                operation="competitor_audit",
                model_name="claude-opus",
                total_cost_usd=Decimal("3.500000"),
                input_tokens=2000,
                output_tokens=800,
                duration_ms=4200,
                status="Success",
                task_id=str(uuid4()),
                user_id=str(uuid4()),
                created_at=datetime.now(UTC),
            )
        ][:limit]


class _FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def notify(self, message: str) -> None:
        self.messages.append(message)


def test_calculate_token_cost() -> None:
    pricing = TokenPricing(
        input_1k_usd=Decimal("0.003"),
        output_1k_usd=Decimal("0.015"),
    )
    cost = calculate_token_cost(input_tokens=1000, output_tokens=1000, pricing=pricing)
    assert cost == Decimal("0.018000")


def test_is_generation_operation() -> None:
    assert is_generation_operation("image_generation_submit") is True
    assert is_generation_operation("face_fix_enhance") is True
    assert is_generation_operation("pain_analysis") is False


def test_evaluate_daily_budget_alert() -> None:
    policy = CostAlertPolicy(
        daily_limit_usd=Decimal("10"),
        generation_spike_ratio=2.0,
        latency_spike_ratio=2.0,
        latency_warn_ms=15000.0,
    )
    today = PeriodCostTotals(
        cost_usd=Decimal("15"),
        events_count=3,
        success_count=3,
        error_count=0,
        timeout_count=0,
        generation_events_count=1,
        generation_cost_usd=Decimal("5"),
        total_input_tokens=0,
        total_output_tokens=0,
        total_duration_ms=1000,
        duration_samples=1,
    )
    alerts = evaluate_cost_alerts(
        policy=policy,
        today=today,
        baseline_week=empty_period_totals(),
    )
    budget = next(a for a in alerts if a.kind == CostAlertKind.DAILY_BUDGET_EXCEEDED)
    assert budget.triggered is True


def test_evaluate_generation_cost_spike() -> None:
    policy = CostAlertPolicy(
        daily_limit_usd=Decimal("1000"),
        generation_spike_ratio=2.0,
        latency_spike_ratio=2.0,
        latency_warn_ms=15000.0,
    )
    today = PeriodCostTotals(
        cost_usd=Decimal("10"),
        events_count=2,
        success_count=2,
        error_count=0,
        timeout_count=0,
        generation_events_count=2,
        generation_cost_usd=Decimal("10"),
        total_input_tokens=0,
        total_output_tokens=0,
        total_duration_ms=0,
        duration_samples=0,
    )
    baseline = PeriodCostTotals(
        cost_usd=Decimal("10"),
        events_count=10,
        success_count=10,
        error_count=0,
        timeout_count=0,
        generation_events_count=10,
        generation_cost_usd=Decimal("10"),
        total_input_tokens=0,
        total_output_tokens=0,
        total_duration_ms=0,
        duration_samples=0,
    )
    # today avg = 5, baseline avg = 1 → spike at ratio 2
    alerts = evaluate_cost_alerts(policy=policy, today=today, baseline_week=baseline)
    spike = next(a for a in alerts if a.kind == CostAlertKind.GENERATION_COST_SPIKE)
    assert spike.triggered is True


def test_profitability_known() -> None:
    metrics = compute_profitability(
        sale_price_usd=Decimal("1.00"),
        avg_generation_cost_usd=Decimal("0.25"),
    )
    assert metrics.known is True
    assert metrics.margin_usd == Decimal("0.750000")
    assert metrics.margin_percent == 75.0


def test_profitability_unknown_when_sale_price_missing() -> None:
    metrics = compute_profitability(
        sale_price_usd=None,
        avg_generation_cost_usd=Decimal("0.25"),
    )
    assert metrics.known is False
    assert metrics.margin_usd is None


def test_provider_breakdown_shares() -> None:
    items = build_provider_breakdown(
        {
            "anthropic": (Decimal("75"), 10),
            "midjourney": (Decimal("25"), 5),
        }
    )
    assert items[0].provider == "anthropic"
    assert items[0].share_percent == 75.0
    assert items[1].share_percent == 25.0


def test_normalize_cost_event_clamps() -> None:
    event = normalize_cost_event(
        CostEventRecord(
            provider="  anthropic  ",
            operation="  pain_analysis  ",
            model_name="  opus  ",
            status=CostCallStatus.SUCCESS,
            total_cost_usd=Decimal("-1"),
            unit_cost_usd=Decimal("-0.5"),
            units=-3,
            input_tokens=-10,
            output_tokens=-2,
            duration_ms=-5,
        )
    )
    assert event.provider == "anthropic"
    assert event.total_cost_usd == Decimal("0.000000")
    assert event.units == 0
    assert event.input_tokens == 0
    assert event.duration_ms == 0


@pytest.mark.asyncio
async def test_cost_analytics_service_dashboard() -> None:
    repo = _FakeRepo()
    notifier = _FakeNotifier()
    service = CostAnalyticsService(
        repository=repo,
        alert_notifier=notifier,
        alert_policy=CostAlertPolicy(
            daily_limit_usd=Decimal("10"),
            generation_spike_ratio=2.0,
            latency_spike_ratio=2.0,
            latency_warn_ms=500.0,
            alerts_enabled=True,
        ),
        generation_sale_price_usd=Decimal("2.00"),
        alert_cooldown_seconds=0,
    )
    snap = await service.get_dashboard(expensive_limit=5, notify_alerts=True)
    assert snap.today.cost_usd == Decimal("12.500000")
    assert snap.week.events_count == 20
    assert snap.month.cost_usd == Decimal("120.000000")
    assert len(snap.by_provider) == 2
    assert snap.avg_generation_cost_usd == quantize_usd(Decimal("16") / Decimal("8"))
    assert snap.profitability.known is True
    assert any(a.triggered for a in snap.alerts)
    assert len(notifier.messages) >= 1

    response = snapshot_to_response(snap)
    assert response.today.cost_usd == snap.today.cost_usd
    assert response.by_provider[0].provider in {"anthropic", "midjourney"}
    assert response.most_expensive[0].operation == "competitor_audit"


@pytest.mark.asyncio
async def test_record_external_call() -> None:
    repo = _FakeRepo()
    service = CostAnalyticsService(
        repository=repo,
        alert_notifier=_FakeNotifier(),
        alert_policy=CostAlertPolicy(
            daily_limit_usd=Decimal("100"),
            generation_spike_ratio=2.0,
            latency_spike_ratio=2.0,
            latency_warn_ms=15000.0,
        ),
    )
    event = CostEventRecord(
        provider="ocr",
        operation="document_ocr",
        model_name="tesseract",
        status=CostCallStatus.SUCCESS,
        total_cost_usd=Decimal("0.01"),
        unit_cost_usd=Decimal("0.01"),
        duration_ms=120,
        task_id=uuid4(),
    )
    await service.record_external_call(event)
    assert len(repo.events) == 1
    assert repo.events[0].provider == "ocr"
