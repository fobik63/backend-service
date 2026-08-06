"""Ports for the isolated WB/Ozon stock-parser micro-module."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.stock_parser import (
    ParseSkuRequest,
    ParsedSkuSnapshot,
    ParserErrorKind,
    ParserHealthStatus,
    ParserHealthView,
    ParserMarketplace,
)


class StockParserPersistencePort(Protocol):
    """Durable health / circuit-breaker state for marketplace parsers."""

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
