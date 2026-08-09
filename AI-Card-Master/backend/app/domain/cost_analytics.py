"""Domain types and pure cost / alert policy for AI Cost Dashboard (plan §80)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CostCallStatus(StrEnum):
    """Terminal status of an external AI / OCR / VTO API call."""

    SUCCESS = "Success"
    ERROR = "Error"
    TIMEOUT = "Timeout"


class CostAlertKind(StrEnum):
    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"
    GENERATION_COST_SPIKE = "generation_cost_spike"
    LATENCY_DEGRADATION = "latency_degradation"


# Operations counted toward "one generation" average cost.
_GENERATION_OPERATION_MARKERS: frozenset[str] = frozenset(
    {
        "image_generation_submit",
        "generation",
        "midjourney",
        "face_fix",
        "vto",
        "virtual_try_on",
    }
)


def is_generation_operation(operation: str) -> bool:
    """Heuristic: treat image-gen / VTO / face-fix ops as generation spend."""

    normalized = operation.strip().lower()
    if not normalized:
        return False
    if normalized in _GENERATION_OPERATION_MARKERS:
        return True
    return any(marker in normalized for marker in _GENERATION_OPERATION_MARKERS)


def quantize_usd(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class TokenPricing(StrictDomainModel):
    """Per-1k-token pricing for LLM providers."""

    input_1k_usd: Decimal = Field(default=Decimal("0"), ge=0)
    output_1k_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("input_1k_usd", "output_1k_usd", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> object:
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
        return value


def calculate_token_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    pricing: TokenPricing,
) -> Decimal:
    """Compute USD cost from token usage and per-1k rates."""

    safe_in = max(0, input_tokens)
    safe_out = max(0, output_tokens)
    total = (
        Decimal(safe_in) / Decimal(1000) * pricing.input_1k_usd
        + Decimal(safe_out) / Decimal(1000) * pricing.output_1k_usd
    )
    return quantize_usd(total)


def calculate_flat_unit_cost(*, units: int, unit_cost_usd: Decimal) -> Decimal:
    safe_units = max(0, units)
    return quantize_usd(Decimal(safe_units) * unit_cost_usd)


@dataclass(frozen=True, slots=True)
class CostEventRecord:
    """One external API call ready for persistence + rollup."""

    provider: str
    operation: str
    model_name: str | None
    status: CostCallStatus
    total_cost_usd: Decimal
    unit_cost_usd: Decimal
    units: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int | None = None
    user_id: UUID | None = None
    generation_job_id: UUID | None = None
    task_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PeriodCostTotals:
    """Spend aggregates for a calendar window."""

    cost_usd: Decimal
    events_count: int
    success_count: int
    error_count: int
    timeout_count: int
    generation_events_count: int
    generation_cost_usd: Decimal
    total_input_tokens: int
    total_output_tokens: int
    total_duration_ms: int
    duration_samples: int

    @property
    def avg_generation_cost_usd(self) -> Decimal | None:
        if self.generation_events_count <= 0:
            return None
        return quantize_usd(
            self.generation_cost_usd / Decimal(self.generation_events_count)
        )

    @property
    def avg_latency_ms(self) -> float | None:
        if self.duration_samples <= 0:
            return None
        return float(self.total_duration_ms) / float(self.duration_samples)


@dataclass(frozen=True, slots=True)
class ProviderCostBreakdown:
    provider: str
    cost_usd: Decimal
    events_count: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class ExpensiveOperation:
    id: str
    provider: str
    operation: str
    model_name: str | None
    total_cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    duration_ms: int | None
    status: str
    task_id: str | None
    user_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProfitabilityMetrics:
    """Margin vs known sale price (None when sale price is not configured)."""

    sale_price_usd: Decimal | None
    avg_generation_cost_usd: Decimal | None
    margin_usd: Decimal | None
    margin_percent: float | None
    known: bool


@dataclass(frozen=True, slots=True)
class CostAlert:
    kind: CostAlertKind
    severity: str
    message: str
    current_value: float
    threshold_value: float
    triggered: bool


@dataclass(frozen=True, slots=True)
class CostAlertPolicy:
    daily_limit_usd: Decimal
    generation_spike_ratio: float
    latency_spike_ratio: float
    latency_warn_ms: float
    alerts_enabled: bool = True


@dataclass(frozen=True, slots=True)
class CostDashboardSnapshot:
    """Full admin Cost Dashboard payload."""

    collected_at: datetime
    today: PeriodCostTotals
    week: PeriodCostTotals
    month: PeriodCostTotals
    by_provider: tuple[ProviderCostBreakdown, ...]
    avg_generation_cost_usd: Decimal | None
    most_expensive: tuple[ExpensiveOperation, ...]
    profitability: ProfitabilityMetrics
    alerts: tuple[CostAlert, ...]
    currency: str = "USD"
    rollup_day_from: date | None = None
    rollup_day_to: date | None = None


def empty_period_totals() -> PeriodCostTotals:
    return PeriodCostTotals(
        cost_usd=Decimal("0"),
        events_count=0,
        success_count=0,
        error_count=0,
        timeout_count=0,
        generation_events_count=0,
        generation_cost_usd=Decimal("0"),
        total_input_tokens=0,
        total_output_tokens=0,
        total_duration_ms=0,
        duration_samples=0,
    )


def merge_period_totals(*parts: PeriodCostTotals) -> PeriodCostTotals:
    cost = Decimal("0")
    gen_cost = Decimal("0")
    events = success = error = timeout = gens = 0
    in_tok = out_tok = dur = samples = 0
    for part in parts:
        cost += part.cost_usd
        gen_cost += part.generation_cost_usd
        events += part.events_count
        success += part.success_count
        error += part.error_count
        timeout += part.timeout_count
        gens += part.generation_events_count
        in_tok += part.total_input_tokens
        out_tok += part.total_output_tokens
        dur += part.total_duration_ms
        samples += part.duration_samples
    return PeriodCostTotals(
        cost_usd=quantize_usd(cost),
        events_count=events,
        success_count=success,
        error_count=error,
        timeout_count=timeout,
        generation_events_count=gens,
        generation_cost_usd=quantize_usd(gen_cost),
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        total_duration_ms=dur,
        duration_samples=samples,
    )


def build_provider_breakdown(
    provider_costs: dict[str, tuple[Decimal, int]],
) -> tuple[ProviderCostBreakdown, ...]:
    grand = sum((cost for cost, _ in provider_costs.values()), Decimal("0"))
    items: list[ProviderCostBreakdown] = []
    for provider, (cost, count) in sorted(
        provider_costs.items(),
        key=lambda item: item[1][0],
        reverse=True,
    ):
        share = float(cost / grand * 100) if grand > 0 else 0.0
        items.append(
            ProviderCostBreakdown(
                provider=provider,
                cost_usd=quantize_usd(cost),
                events_count=count,
                share_percent=round(share, 2),
            )
        )
    return tuple(items)


def compute_profitability(
    *,
    sale_price_usd: Decimal | None,
    avg_generation_cost_usd: Decimal | None,
) -> ProfitabilityMetrics:
    if sale_price_usd is None or sale_price_usd <= 0 or avg_generation_cost_usd is None:
        return ProfitabilityMetrics(
            sale_price_usd=sale_price_usd if sale_price_usd and sale_price_usd > 0 else None,
            avg_generation_cost_usd=avg_generation_cost_usd,
            margin_usd=None,
            margin_percent=None,
            known=False,
        )
    margin = quantize_usd(sale_price_usd - avg_generation_cost_usd)
    pct = float(margin / sale_price_usd * 100) if sale_price_usd > 0 else None
    return ProfitabilityMetrics(
        sale_price_usd=quantize_usd(sale_price_usd),
        avg_generation_cost_usd=avg_generation_cost_usd,
        margin_usd=margin,
        margin_percent=round(pct, 2) if pct is not None else None,
        known=True,
    )


def evaluate_cost_alerts(
    *,
    policy: CostAlertPolicy,
    today: PeriodCostTotals,
    baseline_week: PeriodCostTotals,
) -> tuple[CostAlert, ...]:
    """Pure alert evaluation — no I/O."""

    if not policy.alerts_enabled:
        return ()

    alerts: list[CostAlert] = []

    daily_triggered = today.cost_usd > policy.daily_limit_usd > 0
    alerts.append(
        CostAlert(
            kind=CostAlertKind.DAILY_BUDGET_EXCEEDED,
            severity="critical" if daily_triggered else "info",
            message=(
                f"Daily AI spend ${today.cost_usd} exceeded limit "
                f"${quantize_usd(policy.daily_limit_usd)}."
                if daily_triggered
                else f"Daily AI spend ${today.cost_usd} within budget."
            ),
            current_value=float(today.cost_usd),
            threshold_value=float(policy.daily_limit_usd),
            triggered=daily_triggered,
        )
    )

    today_avg = today.avg_generation_cost_usd
    baseline_avg = baseline_week.avg_generation_cost_usd
    spike_ratio = max(1.0, policy.generation_spike_ratio)
    cost_spike = False
    threshold_cost = 0.0
    if (
        today_avg is not None
        and baseline_avg is not None
        and baseline_avg > 0
        and today.generation_events_count > 0
    ):
        threshold_cost = float(baseline_avg * Decimal(str(spike_ratio)))
        cost_spike = float(today_avg) >= threshold_cost
    alerts.append(
        CostAlert(
            kind=CostAlertKind.GENERATION_COST_SPIKE,
            severity="warning" if cost_spike else "info",
            message=(
                f"Avg generation cost ${today_avg} spiked vs week baseline "
                f"${baseline_avg} (ratio ≥ {spike_ratio})."
                if cost_spike and today_avg is not None and baseline_avg is not None
                else "Generation unit cost is stable vs week baseline."
            ),
            current_value=float(today_avg) if today_avg is not None else 0.0,
            threshold_value=threshold_cost,
            triggered=cost_spike,
        )
    )

    today_latency = today.avg_latency_ms
    baseline_latency = baseline_week.avg_latency_ms
    lat_ratio = max(1.0, policy.latency_spike_ratio)
    latency_triggered = False
    latency_threshold = max(0.0, policy.latency_warn_ms)
    if today_latency is not None:
        ratio_threshold = (
            baseline_latency * lat_ratio if baseline_latency and baseline_latency > 0 else None
        )
        candidates = [latency_threshold]
        if ratio_threshold is not None:
            candidates.append(ratio_threshold)
        latency_threshold = max(candidates)
        latency_triggered = today_latency >= latency_threshold > 0
    alerts.append(
        CostAlert(
            kind=CostAlertKind.LATENCY_DEGRADATION,
            severity="warning" if latency_triggered else "info",
            message=(
                f"External API avg latency {today_latency:.0f}ms exceeds "
                f"threshold {latency_threshold:.0f}ms."
                if latency_triggered and today_latency is not None
                else "External API latency within expected range."
            ),
            current_value=float(today_latency) if today_latency is not None else 0.0,
            threshold_value=float(latency_threshold),
            triggered=latency_triggered,
        )
    )

    return tuple(alerts)


def format_alert_telegram(alert: CostAlert) -> str:
    return (
        f"[AI Cost Alert] {alert.kind.value}\n"
        f"severity: {alert.severity}\n"
        f"{alert.message}\n"
        f"current={alert.current_value} threshold={alert.threshold_value}"
    )


# Re-export field for typing convenience in services.
__all__ = [
    "CostAlert",
    "CostAlertKind",
    "CostAlertPolicy",
    "CostCallStatus",
    "CostDashboardSnapshot",
    "CostEventRecord",
    "ExpensiveOperation",
    "PeriodCostTotals",
    "ProfitabilityMetrics",
    "ProviderCostBreakdown",
    "TokenPricing",
    "build_provider_breakdown",
    "calculate_flat_unit_cost",
    "calculate_token_cost",
    "compute_profitability",
    "empty_period_totals",
    "evaluate_cost_alerts",
    "format_alert_telegram",
    "is_generation_operation",
    "merge_period_totals",
    "quantize_usd",
]
