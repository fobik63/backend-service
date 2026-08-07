"""Ports for AI Cost Dashboard & Resource Analytics (plan §80)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.domain.cost_analytics import (
    CostDashboardSnapshot,
    CostEventRecord,
    ExpensiveOperation,
    PeriodCostTotals,
)


class CostEventRecorderPort(Protocol):
    async def record(self, event: CostEventRecord) -> None:
        """Persist one API cost event and update the matching daily rollup."""


class CostAnalyticsRepositoryPort(Protocol):
    async def record_event(self, event: CostEventRecord) -> None:
        """Write immutable event + upsert daily rollup in one transaction."""

    async def sum_rollups(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> PeriodCostTotals:
        """Aggregate rollup rows for an inclusive UTC day range (no event scan)."""

    async def sum_rollups_by_provider(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> dict[str, tuple[Decimal, int]]:
        """Provider → (cost_usd, events_count) from rollups only."""

    async def list_most_expensive(
        self,
        *,
        since: datetime,
        limit: int = 10,
    ) -> list[ExpensiveOperation]:
        """Top-N costly events via (total_cost_usd, created_at) index."""


class CostAlertNotifierPort(Protocol):
    async def notify(self, message: str) -> None:
        """Best-effort operator alert (Telegram / noop)."""


class CostAnalyticsServicePort(Protocol):
    async def record_external_call(self, event: CostEventRecord) -> None:
        """Log any external AI / OCR / VTO / parser call."""

    async def get_dashboard(
        self,
        *,
        expensive_limit: int = 10,
        notify_alerts: bool = False,
    ) -> CostDashboardSnapshot:
        """Build Cost Dashboard aggregates from daily rollups."""
