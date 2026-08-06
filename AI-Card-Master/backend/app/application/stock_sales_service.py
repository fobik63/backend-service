"""Application use-case: estimate real SKU purchases from stock snapshots (§74).

Loads partitioned ``stock_snapshots``, collapses warehouses per UTC day, then
runs the pure domain classifier (sales / return / restock / transfer).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.stock_parser import StockParserPersistencePort
from app.domain.stock_sales import (
    DailySalesEstimate,
    SalesWindowSummary,
    SnapshotStockPoint,
    StockSalesFilterConfig,
    estimate_real_purchases_24h,
    snapshots_to_sales_window,
)


class StockSalesEstimatorService:
    """Orchestrate persistence → domain math for clean 24h purchase counts."""

    def __init__(
        self,
        persistence: StockParserPersistencePort,
        *,
        config: StockSalesFilterConfig | None = None,
        prefer_hour_utc: int = 3,
    ) -> None:
        self._persistence = persistence
        self._config = config or StockSalesFilterConfig()
        self._prefer_hour_utc = prefer_hour_utc

    async def estimate_window(
        self,
        *,
        sku_id: UUID,
        captured_from: datetime | None = None,
        captured_to: datetime | None = None,
        limit: int = 2000,
    ) -> SalesWindowSummary:
        """Compute clean sales over all snapshots in the given interval."""

        rows = await self._persistence.list_stock_snapshots(
            sku_id=sku_id,
            captured_from=captured_from,
            captured_to=captured_to,
            limit=limit,
        )
        points = tuple(
            SnapshotStockPoint(
                captured_at=row.captured_at,
                warehouse_id=row.warehouse_id,
                quantity=row.quantity,
            )
            for row in rows
        )
        return snapshots_to_sales_window(
            points,
            sku_id=sku_id,
            config=self._config,
            prefer_hour_utc=self._prefer_hour_utc,
        )

    async def estimate_last_24h(
        self,
        *,
        sku_id: UUID,
        as_of: datetime | None = None,
    ) -> DailySalesEstimate | None:
        """Return the latest day-over-day clean purchase estimate, if possible.

        Loads a short lookback (default 4 days) so nightly gaps / duplicate
        parses still yield a usable yesterday→today pair.
        """

        now = as_of if as_of is not None else datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        summary = await self.estimate_window(
            sku_id=sku_id,
            captured_from=now - timedelta(days=4),
            captured_to=now + timedelta(seconds=1),
            limit=2000,
        )
        return summary.last_24h

    def estimate_pair(
        self,
        *,
        stock_yesterday: int,
        stock_today: int,
        gap_hours: float = 24.0,
        warehouse_yesterday: dict[str, int] | None = None,
        warehouse_today: dict[str, int] | None = None,
        sku_id: UUID | None = None,
    ) -> DailySalesEstimate:
        """Pure pair helper (no I/O) for workers / tests / inline checks."""

        return estimate_real_purchases_24h(
            stock_yesterday,
            stock_today,
            gap_hours=gap_hours,
            warehouse_yesterday=warehouse_yesterday,
            warehouse_today=warehouse_today,
            sku_id=sku_id,
            config=self._config,
        )
