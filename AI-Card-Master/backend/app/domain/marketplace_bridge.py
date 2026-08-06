"""Marketplace Data Bridge domain: sales, stocks, orders aggregation windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class BridgePlatform(StrEnum):
    """Marketplaces supported by the sales / stocks / orders bridge."""

    WILDBERRIES = "wildberries"
    OZON = "ozon"


class MarketplaceDataPeriod(StrEnum):
    """Relative reporting window for the personal cabinet dashboard."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    """Inclusive UTC window resolved from a relative period."""

    period: MarketplaceDataPeriod
    date_from: datetime
    date_to: datetime


@dataclass(frozen=True, slots=True)
class SalesMetrics:
    """Aggregated sales for one platform in a window."""

    count: int
    revenue: float
    currency: str = "RUB"


@dataclass(frozen=True, slots=True)
class StocksMetrics:
    """Warehouse / FBO stock snapshot (point-in-time, not period-bound)."""

    sku_count: int
    total_quantity: int


@dataclass(frozen=True, slots=True)
class OrdersMetrics:
    """Aggregated orders for one platform in a window."""

    count: int
    cancelled_count: int


@dataclass(frozen=True, slots=True)
class PlatformDataSlice:
    """Per-marketplace dashboard block for the personal cabinet."""

    platform: BridgePlatform
    connected: bool
    sales: SalesMetrics
    stocks: StocksMetrics
    orders: OrdersMetrics
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AggregatedTotals:
    """Cross-platform rollup for the personal cabinet header."""

    sales: SalesMetrics
    stocks: StocksMetrics
    orders: OrdersMetrics
    connected_platforms: int


@dataclass(frozen=True, slots=True)
class MarketplaceDashboardView:
    """Cross-marketplace aggregate for the user cabinet."""

    period: MarketplaceDataPeriod
    date_from: datetime
    date_to: datetime
    platforms: tuple[PlatformDataSlice, ...]
    totals: AggregatedTotals


_EMPTY_STOCKS = StocksMetrics(sku_count=0, total_quantity=0)
_EMPTY_ORDERS = OrdersMetrics(count=0, cancelled_count=0)


def empty_sales(*, currency: str = "RUB") -> SalesMetrics:
    return SalesMetrics(count=0, revenue=0.0, currency=currency)


def empty_stocks() -> StocksMetrics:
    return _EMPTY_STOCKS


def empty_orders() -> OrdersMetrics:
    return _EMPTY_ORDERS


def resolve_period_window(
    period: MarketplaceDataPeriod,
    *,
    now: datetime | None = None,
) -> PeriodWindow:
    """Map day/week/month to a concrete UTC `[date_from, date_to]` window."""

    anchor = now if now is not None else datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    else:
        anchor = anchor.astimezone(UTC)

    date_to = anchor
    if period is MarketplaceDataPeriod.DAY:
        date_from = date_to - timedelta(days=1)
    elif period is MarketplaceDataPeriod.WEEK:
        date_from = date_to - timedelta(days=7)
    elif period is MarketplaceDataPeriod.MONTH:
        date_from = date_to - timedelta(days=30)
    else:  # pragma: no cover — StrEnum exhaustiveness
        raise ValueError(f"Unsupported period: {period}")

    return PeriodWindow(period=period, date_from=date_from, date_to=date_to)


def sum_sales(parts: tuple[SalesMetrics, ...]) -> SalesMetrics:
    currency = parts[0].currency if parts else "RUB"
    return SalesMetrics(
        count=sum(item.count for item in parts),
        revenue=round(sum(item.revenue for item in parts), 2),
        currency=currency,
    )


def sum_stocks(parts: tuple[StocksMetrics, ...]) -> StocksMetrics:
    return StocksMetrics(
        sku_count=sum(item.sku_count for item in parts),
        total_quantity=sum(item.total_quantity for item in parts),
    )


def sum_orders(parts: tuple[OrdersMetrics, ...]) -> OrdersMetrics:
    return OrdersMetrics(
        count=sum(item.count for item in parts),
        cancelled_count=sum(item.cancelled_count for item in parts),
    )


def build_aggregated_totals(platforms: tuple[PlatformDataSlice, ...]) -> AggregatedTotals:
    """Roll up connected platform slices into cabinet header totals."""

    connected = tuple(item for item in platforms if item.connected and item.error is None)
    return AggregatedTotals(
        sales=sum_sales(tuple(item.sales for item in connected)),
        stocks=sum_stocks(tuple(item.stocks for item in connected)),
        orders=sum_orders(tuple(item.orders for item in connected)),
        connected_platforms=sum(1 for item in platforms if item.connected),
    )


def parse_marketplace_datetime(value: object) -> datetime | None:
    """Parse WB/Ozon ISO-ish timestamps into timezone-aware UTC."""

    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def in_period_window(
    value: datetime | None,
    *,
    window: PeriodWindow,
) -> bool:
    if value is None:
        return False
    return window.date_from <= value <= window.date_to
