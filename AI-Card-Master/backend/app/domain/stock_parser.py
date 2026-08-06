"""Isolated marketplace stock-parser domain (plan §72).

Parsing goes through mobile-app JSON endpoints only (no Selenium/Puppeteer).
Health/circuit-breaker state lives here so FastAPI never imports scraper IO.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParserMarketplace(StrEnum):
    """Supported public storefronts for the stock parser."""

    WILDBERRIES = "wildberries"
    OZON = "ozon"


class ParserHealthStatus(StrEnum):
    """Operational state of a marketplace parser adapter."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"
    DISABLED = "disabled"


class ParserErrorKind(StrEnum):
    """Normalized failure classes counted by the circuit breaker."""

    HTTP_403 = "http_403"
    HTTP_404 = "http_404"
    HTTP_OTHER = "http_other"
    KEY_ERROR = "key_error"
    SCHEMA_DRIFT = "schema_drift"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


# Critical response keys that must survive marketplace mobile-API updates.
WB_REQUIRED_PRODUCT_KEYS: frozenset[str] = frozenset(
    {"id", "name", "salePriceU", "priceU", "sizes"}
)
WB_REQUIRED_SIZE_KEYS: frozenset[str] = frozenset({"stocks"})
OZON_REQUIRED_PRODUCT_KEYS: frozenset[str] = frozenset(
    {"id", "title", "price", "stocks"}
)

CIRCUIT_BREAKER_THRESHOLD = 5


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for parser payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class StockLevel(StrictDomainModel):
    """One warehouse residual for an SKU."""

    warehouse_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0)
    warehouse_name: str | None = Field(default=None, max_length=255)


class ParsedSkuSnapshot(StrictDomainModel):
    """Normalized product snapshot produced by a mobile JSON adapter."""

    marketplace: ParserMarketplace
    sku: str = Field(min_length=1, max_length=64)
    product_url: str | None = Field(default=None, max_length=1024)
    title: str = Field(min_length=1, max_length=500)
    price_kopecks: int = Field(ge=0)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    stocks: tuple[StockLevel, ...] = Field(min_length=0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_stock(self) -> int:
        return sum(item.quantity for item in self.stocks)


class ParseSkuRequest(StrictDomainModel):
    """Single SKU fetch request for a marketplace mobile endpoint."""

    marketplace: ParserMarketplace
    sku: str = Field(min_length=1, max_length=64)
    product_url: str | None = Field(default=None, max_length=1024)

    @field_validator("sku", mode="before")
    @classmethod
    def _strip_sku(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ParserHealthView(StrictDomainModel):
    """Durable health row exposed to workers / ops."""

    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=False)

    id: UUID
    marketplace: ParserMarketplace
    status: ParserHealthStatus
    consecutive_errors: int = Field(ge=0)
    last_error_kind: ParserErrorKind | None = None
    last_error_message: str | None = None
    last_traceback: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    broken_at: datetime | None = None
    alert_sent_at: datetime | None = None
    updated_at: datetime
    created_at: datetime


class ParserRunResult(StrictDomainModel):
    """Outcome of one SKU parse attempt (success or soft-fail)."""

    marketplace: ParserMarketplace
    sku: str
    ok: bool
    snapshot: ParsedSkuSnapshot | None = None
    error_kind: ParserErrorKind | None = None
    error_message: str | None = None
    parser_stopped: bool = False
    health_status: ParserHealthStatus | None = None


class SkuItemView(StrictDomainModel):
    """Tracked marketplace SKU (dimension for raw stock time-series)."""

    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=False)

    id: UUID
    marketplace: ParserMarketplace
    article: str = Field(min_length=1, max_length=64)
    product_url: str = Field(min_length=1, max_length=1024)
    title: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class StockSnapshotView(StrictDomainModel):
    """One raw stock/price observation at a warehouse (fact row)."""

    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=False)

    id: UUID
    sku_id: UUID
    captured_at: datetime
    warehouse_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0)
    price_kopecks: int = Field(ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    created_at: datetime


class StockSnapshotWrite(StrictDomainModel):
    """Insert payload for a partitioned stock_snapshots row."""

    sku_id: UUID
    captured_at: datetime
    warehouse_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0)
    price_kopecks: int = Field(ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)


def month_partition_bounds(captured_at: datetime) -> tuple[datetime, datetime]:
    """Return [start, end) UTC month window for RANGE partitioning."""

    ts = captured_at if captured_at.tzinfo is not None else captured_at.replace(tzinfo=UTC)
    ts = ts.astimezone(UTC)
    start = datetime(ts.year, ts.month, 1, tzinfo=UTC)
    if ts.month == 12:
        end = datetime(ts.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(ts.year, ts.month + 1, 1, tzinfo=UTC)
    return start, end


def stock_snapshot_partition_name(captured_at: datetime) -> str:
    """Physical partition table name for a capture timestamp (yyyy_mm)."""

    start, _ = month_partition_bounds(captured_at)
    return f"stock_snapshots_{start.year:04d}_{start.month:02d}"


def normalize_marketplace(value: str) -> ParserMarketplace:
    """Map common aliases onto the two supported storefronts."""

    normalized = value.strip().casefold()
    aliases = {
        "wb": ParserMarketplace.WILDBERRIES,
        "wildberries": ParserMarketplace.WILDBERRIES,
        "вайлдберриз": ParserMarketplace.WILDBERRIES,
        "ozon": ParserMarketplace.OZON,
        "озон": ParserMarketplace.OZON,
    }
    if normalized not in aliases:
        raise ValueError("marketplace must be wildberries or ozon.")
    return aliases[normalized]


def classify_http_status(status_code: int) -> ParserErrorKind:
    """Map HTTP status codes onto circuit-breaker buckets."""

    if status_code == 403:
        return ParserErrorKind.HTTP_403
    if status_code == 404:
        return ParserErrorKind.HTTP_404
    return ParserErrorKind.HTTP_OTHER


def required_keys_for(marketplace: ParserMarketplace) -> frozenset[str]:
    """Top-level required keys for the marketplace product payload."""

    if marketplace is ParserMarketplace.WILDBERRIES:
        return WB_REQUIRED_PRODUCT_KEYS
    return OZON_REQUIRED_PRODUCT_KEYS
