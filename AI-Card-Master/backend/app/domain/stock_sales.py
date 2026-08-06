"""Real-purchase estimation from consecutive stock snapshots (plan §74).

Base identity (per SKU, after warehouse aggregation)::

    raw_delta = stock_yesterday − stock_today

A positive ``raw_delta`` is a candidate sale. Marketplace residual series are
noisy, so the classifier must neutralize false negatives:

* Sharp stock growth (e.g. 10 → 100) is a **Restock**, never −90 sales.
* Tiny growth of 1–2 units is a buyer **Return**, not negative sales.
* Inter-warehouse transfers cancel at SKU total and must not invent sales.
* Missing / gapped observations yield ``insufficient_data``, not guesses.

The public API is pure (no I/O) and async-safe; workers call it after loading
``StockSnapshotView`` rows from partitioned storage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Iterable, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StockMovementKind(StrEnum):
    """Classification of one day-over-day residual change."""

    SALE = "sale"
    RETURN = "return"
    RESTOCK = "restock"
    STABLE = "stable"
    TRANSFER = "transfer"
    INSUFFICIENT_DATA = "insufficient_data"
    ANOMALY = "anomaly"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for stock-sales payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class StockSalesFilterConfig(StrictDomainModel):
    """Tunable thresholds for restock / return / gap filtering.

    Defaults match the plan §74 contract:
    growth of 1–2 → return; any larger growth → restock (0 sales).
    """

    return_max_units: int = Field(default=2, ge=1, le=20)
    # Absolute growth above return_max is always restock (plan: 10→100).
    # Relative gate catches large % jumps even when absolute is moderate.
    restock_relative_ratio: float = Field(default=0.35, ge=0.0, le=10.0)
    restock_relative_min_units: int = Field(default=3, ge=1, le=10_000)
    # Max hours between consecutive daily anchors before we distrust the pair.
    max_gap_hours: float = Field(default=36.0, ge=12.0, le=168.0)
    # Cap pathological sell-through vs yesterday stock (parser glitch guard).
    max_sell_through_ratio: float = Field(default=1.0, ge=0.5, le=1.0)
    # Transfer detection: opposing warehouse deltas that nearly cancel.
    transfer_balance_tolerance_units: int = Field(default=1, ge=0, le=50)
    transfer_min_moved_units: int = Field(default=3, ge=1, le=10_000)

    @model_validator(mode="after")
    def _validate_bands(self) -> StockSalesFilterConfig:
        if self.restock_relative_min_units <= self.return_max_units:
            raise ValueError(
                "restock_relative_min_units must be > return_max_units "
                "so returns and restocks do not overlap."
            )
        return self


class WarehouseQuantity(StrictDomainModel):
    """One warehouse residual at a capture instant."""

    warehouse_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0)


class DailyStockAnchor(StrictDomainModel):
    """SKU-level residual for one calendar day (UTC), warehouses collapsed."""

    day: date
    captured_at: datetime
    total_quantity: int = Field(ge=0)
    warehouses: tuple[WarehouseQuantity, ...] = Field(default_factory=tuple)

    @field_validator("captured_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @property
    def warehouse_map(self) -> dict[str, int]:
        return {item.warehouse_id: item.quantity for item in self.warehouses}


class DailySalesEstimate(StrictDomainModel):
    """Clean purchase count for one 24h step between two anchors."""

    sku_id: UUID | None = None
    day: date
    stock_yesterday: int = Field(ge=0)
    stock_today: int = Field(ge=0)
    raw_delta: int
    units_sold: int = Field(ge=0)
    units_returned: int = Field(ge=0)
    units_restocked: int = Field(ge=0)
    kind: StockMovementKind
    confidence: float = Field(ge=0.0, le=1.0)
    gap_hours: float = Field(ge=0.0)
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_reliable(self) -> bool:
        return self.kind in {
            StockMovementKind.SALE,
            StockMovementKind.RETURN,
            StockMovementKind.RESTOCK,
            StockMovementKind.STABLE,
            StockMovementKind.TRANSFER,
        } and self.confidence >= 0.5


class SalesWindowSummary(StrictDomainModel):
    """Aggregated clean purchases over a multi-day observation window."""

    sku_id: UUID | None = None
    days: tuple[DailySalesEstimate, ...] = Field(default_factory=tuple)
    total_units_sold: int = Field(ge=0)
    total_units_returned: int = Field(ge=0)
    total_units_restocked: int = Field(ge=0)
    reliable_day_count: int = Field(ge=0)
    skipped_day_count: int = Field(ge=0)
    avg_daily_sales: float = Field(ge=0.0)
    last_24h: DailySalesEstimate | None = None

    @property
    def net_units(self) -> int:
        """Gross purchases minus observed returns (never negative)."""

        return max(0, self.total_units_sold - self.total_units_returned)


class SnapshotStockPoint(StrictDomainModel):
    """Minimal snapshot projection accepted by the aggregator."""

    captured_at: datetime
    warehouse_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0)

    @field_validator("captured_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def raw_sales_delta(stock_yesterday: int, stock_today: int) -> int:
    """Naive formula from the plan: yesterday − today (may be negative)."""

    if stock_yesterday < 0 or stock_today < 0:
        raise ValueError("stock quantities must be non-negative.")
    return int(stock_yesterday) - int(stock_today)


def is_return_growth(*, growth_units: int, config: StockSalesFilterConfig) -> bool:
    """True when inventory grew by 1–2 units (buyer return)."""

    return 1 <= growth_units <= config.return_max_units


def is_restock_growth(*, growth_units: int, config: StockSalesFilterConfig) -> bool:
    """True when growth is a supply injection, not a tiny return.

    Absolute rule (plan §74): any jump larger than ``return_max_units``
    (default 2) is treated as restock → 0 sales for that day.
    """

    return growth_units > config.return_max_units


def restock_severity_ratio(*, stock_yesterday: int, growth_units: int) -> float:
    """How large the restock is vs prior residual (∞-like when yesterday was 0)."""

    if stock_yesterday <= 0:
        return float(growth_units)
    return growth_units / float(stock_yesterday)

def detect_warehouse_transfer(
    yesterday: Mapping[str, int],
    today: Mapping[str, int],
    *,
    config: StockSalesFilterConfig,
) -> tuple[bool, int]:
    """Detect inter-warehouse relocation that nets near-zero at SKU level.

    Returns ``(is_transfer, moved_units)`` where ``moved_units`` is the volume
    that left one set of warehouses and appeared in others.
    """

    ids = set(yesterday) | set(today)
    if not ids:
        return False, 0

    decreases = 0
    increases = 0
    for wid in ids:
        delta = int(today.get(wid, 0)) - int(yesterday.get(wid, 0))
        if delta > 0:
            increases += delta
        elif delta < 0:
            decreases += -delta

    if decreases < config.transfer_min_moved_units:
        return False, 0
    if increases < config.transfer_min_moved_units:
        return False, 0

    imbalance = abs(increases - decreases)
    if imbalance <= config.transfer_balance_tolerance_units:
        return True, min(increases, decreases)
    return False, 0


def classify_stock_movement(
    stock_yesterday: int,
    stock_today: int,
    *,
    day: date,
    gap_hours: float,
    warehouse_yesterday: Mapping[str, int] | None = None,
    warehouse_today: Mapping[str, int] | None = None,
    sku_id: UUID | None = None,
    config: StockSalesFilterConfig | None = None,
) -> DailySalesEstimate:
    """Apply plan §74 formula + edge-case filter for one 24h step.

    Returns clean ``units_sold`` for real purchases (never negative).
    """

    cfg = config or StockSalesFilterConfig()
    notes: list[str] = []

    if stock_yesterday < 0 or stock_today < 0:
        return DailySalesEstimate(
            sku_id=sku_id,
            day=day,
            stock_yesterday=max(0, stock_yesterday),
            stock_today=max(0, stock_today),
            raw_delta=0,
            units_sold=0,
            units_returned=0,
            units_restocked=0,
            kind=StockMovementKind.ANOMALY,
            confidence=0.0,
            gap_hours=max(0.0, gap_hours),
            notes=("negative_stock_rejected",),
        )

    raw = raw_sales_delta(stock_yesterday, stock_today)

    if gap_hours > cfg.max_gap_hours:
        return DailySalesEstimate(
            sku_id=sku_id,
            day=day,
            stock_yesterday=stock_yesterday,
            stock_today=stock_today,
            raw_delta=raw,
            units_sold=0,
            units_returned=0,
            units_restocked=0,
            kind=StockMovementKind.INSUFFICIENT_DATA,
            confidence=0.0,
            gap_hours=gap_hours,
            notes=(
                f"gap_hours={gap_hours:.1f}>{cfg.max_gap_hours}",
                "skipped_untrusted_interval",
            ),
        )

    # Warehouse relocation must be checked before treating net drop as sales.
    if warehouse_yesterday is not None and warehouse_today is not None:
        is_xfer, moved = detect_warehouse_transfer(
            warehouse_yesterday,
            warehouse_today,
            config=cfg,
        )
        if is_xfer and abs(raw) <= cfg.transfer_balance_tolerance_units:
            return DailySalesEstimate(
                sku_id=sku_id,
                day=day,
                stock_yesterday=stock_yesterday,
                stock_today=stock_today,
                raw_delta=raw,
                units_sold=0,
                units_returned=0,
                units_restocked=0,
                kind=StockMovementKind.TRANSFER,
                confidence=_clamp01(0.85 - (gap_hours / (cfg.max_gap_hours * 4.0))),
                gap_hours=gap_hours,
                notes=(f"warehouse_transfer_moved={moved}",),
            )

    # --- growth branch: never emit negative sales ---
    if raw < 0:
        growth = -raw
        if is_return_growth(growth_units=growth, config=cfg):
            notes.append("buyer_return_1_to_2")
            return DailySalesEstimate(
                sku_id=sku_id,
                day=day,
                stock_yesterday=stock_yesterday,
                stock_today=stock_today,
                raw_delta=raw,
                units_sold=0,
                units_returned=growth,
                units_restocked=0,
                kind=StockMovementKind.RETURN,
                confidence=_clamp01(0.9 - (gap_hours / (cfg.max_gap_hours * 5.0))),
                gap_hours=gap_hours,
                notes=tuple(notes),
            )

        # Plan example: 10 → 100 ⇒ restock, sales = 0 (ignore the day).
        if not is_restock_growth(growth_units=growth, config=cfg):
            # Defensive: any leftover growth band still must not invent sales.
            notes.append("unclassified_growth_treated_as_restock")
        notes.append("restock_spike_ignored")
        severity = restock_severity_ratio(
            stock_yesterday=stock_yesterday,
            growth_units=growth,
        )
        notes.append(
            f"restock_growth={growth}_vs_prev={stock_yesterday}_ratio={severity:.2f}",
        )
        if severity >= cfg.restock_relative_ratio:
            notes.append("sharp_relative_restock")
        return DailySalesEstimate(
            sku_id=sku_id,
            day=day,
            stock_yesterday=stock_yesterday,
            stock_today=stock_today,
            raw_delta=raw,
            units_sold=0,
            units_returned=0,
            units_restocked=growth,
            kind=StockMovementKind.RESTOCK,
            confidence=_clamp01(0.95 - (gap_hours / (cfg.max_gap_hours * 5.0))),
            gap_hours=gap_hours,
            notes=tuple(notes),
        )

    if raw == 0:
        return DailySalesEstimate(
            sku_id=sku_id,
            day=day,
            stock_yesterday=stock_yesterday,
            stock_today=stock_today,
            raw_delta=0,
            units_sold=0,
            units_returned=0,
            units_restocked=0,
            kind=StockMovementKind.STABLE,
            confidence=_clamp01(0.95 - (gap_hours / (cfg.max_gap_hours * 5.0))),
            gap_hours=gap_hours,
            notes=("flat_residual",),
        )

    # --- drop branch: real purchases ---
    units = raw
    max_possible = int(stock_yesterday * cfg.max_sell_through_ratio)
    if units > max_possible:
        notes.append(f"clamped_sell_through_{units}_to_{max_possible}")
        units = max_possible

    # Confidence decays with gap and with extreme sell-through (possible glitch).
    sell_through = units / stock_yesterday if stock_yesterday > 0 else 1.0
    confidence = 0.98
    confidence -= min(0.25, abs(gap_hours - 24.0) / 100.0)
    if sell_through >= 0.95 and stock_yesterday >= 20:
        confidence -= 0.15
        notes.append("near_total_sell_through")
    if stock_today == 0 and stock_yesterday > 0:
        notes.append("sold_out")

    return DailySalesEstimate(
        sku_id=sku_id,
        day=day,
        stock_yesterday=stock_yesterday,
        stock_today=stock_today,
        raw_delta=raw,
        units_sold=units,
        units_returned=0,
        units_restocked=0,
        kind=StockMovementKind.SALE,
        confidence=_clamp01(confidence),
        gap_hours=gap_hours,
        notes=tuple(notes),
    )


def _gap_hours(previous: datetime, current: datetime) -> float:
    prev = previous if previous.tzinfo else previous.replace(tzinfo=UTC)
    curr = current if current.tzinfo else current.replace(tzinfo=UTC)
    return max(0.0, (curr.astimezone(UTC) - prev.astimezone(UTC)).total_seconds() / 3600.0)


def build_daily_stock_anchors(
    snapshots: Sequence[SnapshotStockPoint],
    *,
    prefer_hour_utc: int = 3,
) -> list[DailyStockAnchor]:
    """Collapse raw warehouse rows into one anchor per UTC calendar day.

    When a day has multiple parse batches, prefer the batch whose clock is
    closest to ``prefer_hour_utc`` (nightly Celery Beat default = 03:00),
    breaking ties by latest ``captured_at``.
    """

    if not snapshots:
        return []

    # Group rows by (day, exact capture timestamp) → warehouse quantities.
    batches: dict[date, dict[datetime, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for point in snapshots:
        ts = point.captured_at.astimezone(UTC)
        day = ts.date()
        batches[day][ts][point.warehouse_id] = int(point.quantity)

    anchors: list[DailyStockAnchor] = []
    target = timedelta(hours=prefer_hour_utc)

    for day in sorted(batches):
        candidates = batches[day]

        def _score(ts: datetime) -> tuple[float, float]:
            # Closer to prefer_hour wins; later timestamp breaks ties.
            tod = timedelta(
                hours=ts.hour,
                minutes=ts.minute,
                seconds=ts.second,
                microseconds=ts.microsecond,
            )
            distance = abs((tod - target).total_seconds())
            return (distance, -ts.timestamp())

        best_ts = min(candidates.keys(), key=_score)
        wh_map = candidates[best_ts]
        warehouses = tuple(
            WarehouseQuantity(warehouse_id=wid, quantity=qty)
            for wid, qty in sorted(wh_map.items())
        )
        total = sum(item.quantity for item in warehouses)
        anchors.append(
            DailyStockAnchor(
                day=day,
                captured_at=best_ts,
                total_quantity=total,
                warehouses=warehouses,
            )
        )
    return anchors


def estimate_sales_between_anchors(
    previous: DailyStockAnchor,
    current: DailyStockAnchor,
    *,
    sku_id: UUID | None = None,
    config: StockSalesFilterConfig | None = None,
) -> DailySalesEstimate:
    """Classify the movement between two consecutive daily anchors."""

    return classify_stock_movement(
        previous.total_quantity,
        current.total_quantity,
        day=current.day,
        gap_hours=_gap_hours(previous.captured_at, current.captured_at),
        warehouse_yesterday=previous.warehouse_map,
        warehouse_today=current.warehouse_map,
        sku_id=sku_id,
        config=config,
    )


def estimate_sales_window(
    anchors: Sequence[DailyStockAnchor],
    *,
    sku_id: UUID | None = None,
    config: StockSalesFilterConfig | None = None,
) -> SalesWindowSummary:
    """Walk consecutive daily anchors and sum clean purchases.

    Days classified as restock / insufficient_data contribute 0 sales (plan:
    ignore restock days). Returns are tracked separately and netted via
    ``SalesWindowSummary.net_units``.
    """

    cfg = config or StockSalesFilterConfig()
    if len(anchors) < 2:
        return SalesWindowSummary(
            sku_id=sku_id,
            days=(),
            total_units_sold=0,
            total_units_returned=0,
            total_units_restocked=0,
            reliable_day_count=0,
            skipped_day_count=0 if not anchors else 1,
            avg_daily_sales=0.0,
            last_24h=None,
        )

    ordered = sorted(anchors, key=lambda a: (a.day, a.captured_at))
    days: list[DailySalesEstimate] = []
    for prev, curr in zip(ordered, ordered[1:]):
        # Skip calendar holes larger than one day only via gap_hours gate.
        days.append(
            estimate_sales_between_anchors(
                prev,
                curr,
                sku_id=sku_id,
                config=cfg,
            )
        )

    sold = sum(d.units_sold for d in days)
    returned = sum(d.units_returned for d in days)
    restocked = sum(d.units_restocked for d in days)
    reliable = [d for d in days if d.is_reliable]
    skipped = len(days) - len(reliable)
    avg = (sold / len(reliable)) if reliable else 0.0

    return SalesWindowSummary(
        sku_id=sku_id,
        days=tuple(days),
        total_units_sold=sold,
        total_units_returned=returned,
        total_units_restocked=restocked,
        reliable_day_count=len(reliable),
        skipped_day_count=skipped,
        avg_daily_sales=round(avg, 4),
        last_24h=days[-1] if days else None,
    )


def estimate_real_purchases_24h(
    stock_yesterday: int,
    stock_today: int,
    *,
    day: date | None = None,
    gap_hours: float = 24.0,
    warehouse_yesterday: Mapping[str, int] | None = None,
    warehouse_today: Mapping[str, int] | None = None,
    sku_id: UUID | None = None,
    config: StockSalesFilterConfig | None = None,
) -> DailySalesEstimate:
    """Convenience entry: clean purchases for a single yesterday→today pair."""

    return classify_stock_movement(
        stock_yesterday,
        stock_today,
        day=day or datetime.now(UTC).date(),
        gap_hours=gap_hours,
        warehouse_yesterday=warehouse_yesterday,
        warehouse_today=warehouse_today,
        sku_id=sku_id,
        config=config,
    )


def snapshots_to_sales_window(
    snapshots: Iterable[SnapshotStockPoint],
    *,
    sku_id: UUID | None = None,
    config: StockSalesFilterConfig | None = None,
    prefer_hour_utc: int = 3,
) -> SalesWindowSummary:
    """End-to-end pure pipeline: raw rows → daily anchors → clean sales."""

    points = tuple(snapshots)
    anchors = build_daily_stock_anchors(points, prefer_hour_utc=prefer_hour_utc)
    return estimate_sales_window(anchors, sku_id=sku_id, config=config)
