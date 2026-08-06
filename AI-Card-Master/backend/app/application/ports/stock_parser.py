"""Ports for the isolated WB/Ozon stock-parser micro-module."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence
from uuid import UUID

from app.domain.stock_parser import (
    ParseSkuRequest,
    ParsedSkuSnapshot,
    ParserErrorKind,
    ParserHealthStatus,
    ParserHealthView,
    ParserMarketplace,
    SkuItemView,
    StockSnapshotView,
    StockSnapshotWrite,
)


class StockParserPersistencePort(Protocol):
    """Durable health / circuit-breaker + raw SKU / snapshot storage."""

    async def get_or_create_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        """Return the health row, creating a healthy row on first use."""

    async def get_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView | None:
        """Load health without creating."""

    async def record_success(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        """Reset consecutive errors and mark healthy (unless disabled)."""

    async def record_failure(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        mark_broken: bool,
    ) -> ParserHealthView:
        """Increment consecutive errors; optionally flip status to broken."""

    async def mark_alert_sent(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        """Stamp that a Telegram broken-alert was delivered."""

    async def set_status(
        self,
        *,
        marketplace: ParserMarketplace,
        status: ParserHealthStatus,
    ) -> ParserHealthView:
        """Manual / ops status override (e.g. re-enable after fix)."""

    async def upsert_sku_item(
        self,
        *,
        marketplace: ParserMarketplace,
        article: str,
        product_url: str,
        title: str | None = None,
        is_active: bool = True,
    ) -> SkuItemView:
        """Create or refresh a tracked SKU row."""

    async def get_sku_item(
        self, *, marketplace: ParserMarketplace, article: str
    ) -> SkuItemView | None:
        """Lookup SKU by marketplace + article."""

    async def list_active_sku_items(
        self, *, marketplace: ParserMarketplace | None = None
    ) -> list[SkuItemView]:
        """Return tracked SKUs for nightly parser Beat jobs."""

    async def ensure_stock_snapshot_partition(
        self, *, captured_at: datetime
    ) -> str:
        """Ensure the monthly RANGE partition for ``captured_at`` exists."""

    async def insert_stock_snapshots(
        self, *, rows: Sequence[StockSnapshotWrite]
    ) -> list[StockSnapshotView]:
        """Bulk-insert raw warehouse observations into partitioned storage."""

    async def list_stock_snapshots(
        self,
        *,
        sku_id: UUID,
        captured_from: datetime | None = None,
        captured_to: datetime | None = None,
        limit: int = 500,
    ) -> list[StockSnapshotView]:
        """Time-ordered snapshots for one SKU (uses sku_id + captured_at index)."""


class MarketplaceMobileParserPort(Protocol):
    """Fetch one SKU via marketplace mobile JSON endpoints (httpx only)."""

    marketplace: ParserMarketplace

    async def fetch_sku(self, request: ParseSkuRequest) -> ParsedSkuSnapshot:
        """Return a normalized snapshot or raise a typed parser error."""

    async def aclose(self) -> None:
        """Release HTTP / proxy resources."""


class ParserAlertPort(Protocol):
    """Notify ops when the parser circuit trips to broken."""

    async def send_broken_alert(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        consecutive_errors: int,
        health_id: UUID,
    ) -> bool:
        """Return True when Telegram accepted at least one message chunk."""
