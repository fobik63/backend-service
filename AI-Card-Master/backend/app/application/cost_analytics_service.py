"""Application service: AI Cost Dashboard & alerts (plan §80)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.application.ports.cost_analytics import (
    CostAlertNotifierPort,
    CostAnalyticsRepositoryPort,
)
from app.domain.cost_analytics import (
    CostAlertPolicy,
    CostDashboardSnapshot,
    CostEventRecord,
    build_provider_breakdown,
    compute_profitability,
    empty_period_totals,
    evaluate_cost_alerts,
    format_alert_telegram,
    quantize_usd,
)


class CostAnalyticsService:
    """Orchestrates cost recording, rollup-backed analytics, and budget alerts."""

    def __init__(
        self,
        *,
        repository: CostAnalyticsRepositoryPort,
        alert_notifier: CostAlertNotifierPort,
        alert_policy: CostAlertPolicy,
        generation_sale_price_usd: Decimal | None = None,
        alert_cooldown_seconds: float = 3600.0,
    ) -> None:
        self._repository = repository
        self._notifier = alert_notifier
        self._policy = alert_policy
        self._sale_price = generation_sale_price_usd
        self._alert_cooldown_seconds = max(0.0, alert_cooldown_seconds)
        self._last_alert_sent: dict[str, float] = {}

    async def record_external_call(self, event: CostEventRecord) -> None:
        """Persist one external API call (fail-open at adapter layer)."""

        await self._repository.record_event(event)

    async def get_dashboard(
        self,
        *,
        expensive_limit: int = 10,
        notify_alerts: bool = False,
        now: datetime | None = None,
    ) -> CostDashboardSnapshot:
        """Assemble today / week / month spend without full-table scans."""

        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        else:
            moment = moment.astimezone(UTC)

        today = moment.date()
        week_from = today - timedelta(days=6)
        month_from = today - timedelta(days=29)
        # Baseline for spikes: previous 7 full days before today.
        baseline_from = today - timedelta(days=7)
        baseline_to = today - timedelta(days=1)

        today_totals = await self._repository.sum_rollups(day_from=today, day_to=today)
        week_totals = await self._repository.sum_rollups(day_from=week_from, day_to=today)
        month_totals = await self._repository.sum_rollups(day_from=month_from, day_to=today)
        if baseline_to >= baseline_from:
            baseline = await self._repository.sum_rollups(
                day_from=baseline_from,
                day_to=baseline_to,
            )
        else:
            baseline = empty_period_totals()

        provider_map = await self._repository.sum_rollups_by_provider(
            day_from=month_from,
            day_to=today,
        )
        by_provider = build_provider_breakdown(provider_map)

        since = datetime(month_from.year, month_from.month, month_from.day, tzinfo=UTC)
        expensive = await self._repository.list_most_expensive(
            since=since,
            limit=max(1, min(expensive_limit, 50)),
        )

        avg_gen = week_totals.avg_generation_cost_usd
        profitability = compute_profitability(
            sale_price_usd=self._sale_price,
            avg_generation_cost_usd=avg_gen,
        )
        alerts = evaluate_cost_alerts(
            policy=self._policy,
            today=today_totals,
            baseline_week=baseline,
        )

        if notify_alerts:
            await self._maybe_notify(alerts)

        return CostDashboardSnapshot(
            collected_at=moment,
            today=today_totals,
            week=week_totals,
            month=month_totals,
            by_provider=by_provider,
            avg_generation_cost_usd=avg_gen,
            most_expensive=tuple(expensive),
            profitability=profitability,
            alerts=alerts,
            rollup_day_from=month_from,
            rollup_day_to=today,
        )

    async def _maybe_notify(self, alerts: tuple) -> None:
        import time

        now_mono = time.monotonic()
        for alert in alerts:
            if not alert.triggered:
                continue
            key = alert.kind.value
            last = self._last_alert_sent.get(key)
            if (
                last is not None
                and self._alert_cooldown_seconds > 0
                and (now_mono - last) < self._alert_cooldown_seconds
            ):
                continue
            await self._notifier.notify(format_alert_telegram(alert))
            self._last_alert_sent[key] = now_mono


def utc_day(value: datetime | None = None) -> date:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).date()


def normalize_cost_event(event: CostEventRecord) -> CostEventRecord:
    """Clamp numeric fields before persistence."""

    return CostEventRecord(
        provider=event.provider.strip()[:64] or "unknown",
        operation=event.operation.strip()[:128] or "unknown",
        model_name=(event.model_name.strip()[:128] if event.model_name else None),
        status=event.status,
        total_cost_usd=quantize_usd(max(Decimal("0"), event.total_cost_usd)),
        unit_cost_usd=quantize_usd(max(Decimal("0"), event.unit_cost_usd)),
        units=max(0, event.units),
        input_tokens=max(0, event.input_tokens),
        output_tokens=max(0, event.output_tokens),
        duration_ms=None if event.duration_ms is None else max(0, event.duration_ms),
        user_id=event.user_id,
        generation_job_id=event.generation_job_id,
        task_id=event.task_id,
        metadata=event.metadata,
        created_at=event.created_at,
    )
