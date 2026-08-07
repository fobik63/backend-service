"""Pydantic schemas for AI Cost Dashboard admin API (plan §80)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.cost_analytics import CostDashboardSnapshot


class StrictCostModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class PeriodCostTotalsResponse(StrictCostModel):
    cost_usd: Decimal
    events_count: int = Field(..., ge=0)
    success_count: int = Field(..., ge=0)
    error_count: int = Field(..., ge=0)
    timeout_count: int = Field(..., ge=0)
    generation_events_count: int = Field(..., ge=0)
    generation_cost_usd: Decimal
    total_input_tokens: int = Field(..., ge=0)
    total_output_tokens: int = Field(..., ge=0)
    avg_generation_cost_usd: Decimal | None = None
    avg_latency_ms: float | None = None


class ProviderCostBreakdownResponse(StrictCostModel):
    provider: str
    cost_usd: Decimal
    events_count: int = Field(..., ge=0)
    share_percent: float = Field(..., ge=0)


class ExpensiveOperationResponse(StrictCostModel):
    id: str
    provider: str
    operation: str
    model_name: str | None = None
    total_cost_usd: Decimal
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    duration_ms: int | None = None
    status: str
    task_id: str | None = None
    user_id: str | None = None
    created_at: datetime


class ProfitabilityResponse(StrictCostModel):
    sale_price_usd: Decimal | None = None
    avg_generation_cost_usd: Decimal | None = None
    margin_usd: Decimal | None = None
    margin_percent: float | None = None
    known: bool


class CostAlertResponse(StrictCostModel):
    kind: Literal[
        "daily_budget_exceeded",
        "generation_cost_spike",
        "latency_degradation",
    ]
    severity: str
    message: str
    current_value: float
    threshold_value: float
    triggered: bool


class CostDashboardResponse(StrictCostModel):
    """GET /api/v1/admin/costs payload."""

    collected_at: datetime
    currency: str = "USD"
    today: PeriodCostTotalsResponse
    week: PeriodCostTotalsResponse
    month: PeriodCostTotalsResponse
    by_provider: list[ProviderCostBreakdownResponse]
    avg_generation_cost_usd: Decimal | None = None
    most_expensive: list[ExpensiveOperationResponse]
    profitability: ProfitabilityResponse
    alerts: list[CostAlertResponse]
    rollup_day_from: date | None = None
    rollup_day_to: date | None = None


def _period_to_response(period) -> PeriodCostTotalsResponse:
    return PeriodCostTotalsResponse(
        cost_usd=period.cost_usd,
        events_count=period.events_count,
        success_count=period.success_count,
        error_count=period.error_count,
        timeout_count=period.timeout_count,
        generation_events_count=period.generation_events_count,
        generation_cost_usd=period.generation_cost_usd,
        total_input_tokens=period.total_input_tokens,
        total_output_tokens=period.total_output_tokens,
        avg_generation_cost_usd=period.avg_generation_cost_usd,
        avg_latency_ms=period.avg_latency_ms,
    )


def snapshot_to_response(snapshot: CostDashboardSnapshot) -> CostDashboardResponse:
    return CostDashboardResponse(
        collected_at=snapshot.collected_at,
        currency=snapshot.currency,
        today=_period_to_response(snapshot.today),
        week=_period_to_response(snapshot.week),
        month=_period_to_response(snapshot.month),
        by_provider=[
            ProviderCostBreakdownResponse(
                provider=item.provider,
                cost_usd=item.cost_usd,
                events_count=item.events_count,
                share_percent=item.share_percent,
            )
            for item in snapshot.by_provider
        ],
        avg_generation_cost_usd=snapshot.avg_generation_cost_usd,
        most_expensive=[
            ExpensiveOperationResponse(
                id=item.id,
                provider=item.provider,
                operation=item.operation,
                model_name=item.model_name,
                total_cost_usd=item.total_cost_usd,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                duration_ms=item.duration_ms,
                status=item.status,
                task_id=item.task_id,
                user_id=item.user_id,
                created_at=item.created_at,
            )
            for item in snapshot.most_expensive
        ],
        profitability=ProfitabilityResponse(
            sale_price_usd=snapshot.profitability.sale_price_usd,
            avg_generation_cost_usd=snapshot.profitability.avg_generation_cost_usd,
            margin_usd=snapshot.profitability.margin_usd,
            margin_percent=snapshot.profitability.margin_percent,
            known=snapshot.profitability.known,
        ),
        alerts=[
            CostAlertResponse(
                kind=alert.kind.value,  # type: ignore[arg-type]
                severity=alert.severity,
                message=alert.message,
                current_value=alert.current_value,
                threshold_value=alert.threshold_value,
                triggered=alert.triggered,
            )
            for alert in snapshot.alerts
        ],
        rollup_day_from=snapshot.rollup_day_from,
        rollup_day_to=snapshot.rollup_day_to,
    )
