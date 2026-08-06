"""Unit tests for stock→sales math with edge-case filters (plan §74)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.stock_sales import (
    DailyStockAnchor,
    SnapshotStockPoint,
    StockMovementKind,
    StockSalesFilterConfig,
    WarehouseQuantity,
    build_daily_stock_anchors,
    classify_stock_movement,
    estimate_real_purchases_24h,
    estimate_sales_window,
    raw_sales_delta,
    snapshots_to_sales_window,
)


def _ts(day: date, hour: int = 3, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def test_raw_formula_yesterday_minus_today() -> None:
    assert raw_sales_delta(100, 85) == 15
    assert raw_sales_delta(10, 100) == -90


def test_sale_when_stock_drops() -> None:
    result = estimate_real_purchases_24h(100, 85, day=date(2026, 8, 7))
    assert result.kind is StockMovementKind.SALE
    assert result.units_sold == 15
    assert result.units_returned == 0
    assert result.units_restocked == 0
    assert result.is_reliable is True


def test_restock_spike_is_zero_sales_not_negative() -> None:
    """Plan example: yesterday 10, today 100 → Restock, not −90 sales."""

    result = estimate_real_purchases_24h(10, 100, day=date(2026, 8, 7))
    assert result.kind is StockMovementKind.RESTOCK
    assert result.raw_delta == -90
    assert result.units_sold == 0
    assert result.units_restocked == 90
    assert result.is_reliable is True


def test_return_growth_of_one_or_two_units() -> None:
    one = estimate_real_purchases_24h(50, 51, day=date(2026, 8, 7))
    assert one.kind is StockMovementKind.RETURN
    assert one.units_sold == 0
    assert one.units_returned == 1

    two = estimate_real_purchases_24h(50, 52, day=date(2026, 8, 7))
    assert two.kind is StockMovementKind.RETURN
    assert two.units_returned == 2
    assert two.units_sold == 0


def test_growth_of_three_is_restock_not_return() -> None:
    result = estimate_real_purchases_24h(50, 53, day=date(2026, 8, 7))
    assert result.kind is StockMovementKind.RESTOCK
    assert result.units_sold == 0
    assert result.units_restocked == 3
    assert result.units_returned == 0


def test_stable_residual() -> None:
    result = estimate_real_purchases_24h(40, 40, day=date(2026, 8, 7))
    assert result.kind is StockMovementKind.STABLE
    assert result.units_sold == 0


def test_sold_out_counts_full_sell_through() -> None:
    result = estimate_real_purchases_24h(12, 0, day=date(2026, 8, 7))
    assert result.kind is StockMovementKind.SALE
    assert result.units_sold == 12
    assert "sold_out" in result.notes


def test_gap_too_large_yields_insufficient_data() -> None:
    result = estimate_real_purchases_24h(
        80,
        60,
        day=date(2026, 8, 7),
        gap_hours=72.0,
    )
    assert result.kind is StockMovementKind.INSUFFICIENT_DATA
    assert result.units_sold == 0
    assert result.is_reliable is False


def test_warehouse_transfer_not_counted_as_sales() -> None:
    result = classify_stock_movement(
        100,
        100,
        day=date(2026, 8, 7),
        gap_hours=24.0,
        warehouse_yesterday={"wh-a": 70, "wh-b": 30},
        warehouse_today={"wh-a": 40, "wh-b": 60},
    )
    assert result.kind is StockMovementKind.TRANSFER
    assert result.units_sold == 0
    assert result.raw_delta == 0


def test_net_sale_when_partial_transfer_plus_real_drop() -> None:
    # Total 100 → 90 (10 sold). Warehouses reshuffled but net drop remains.
    result = classify_stock_movement(
        100,
        90,
        day=date(2026, 8, 7),
        gap_hours=24.0,
        warehouse_yesterday={"wh-a": 70, "wh-b": 30},
        warehouse_today={"wh-a": 50, "wh-b": 40},
    )
    assert result.kind is StockMovementKind.SALE
    assert result.units_sold == 10


def test_build_daily_anchors_prefers_03_utc_and_sums_warehouses() -> None:
    day = date(2026, 8, 6)
    points = [
        SnapshotStockPoint(captured_at=_ts(day, 2, 50), warehouse_id="a", quantity=10),
        SnapshotStockPoint(captured_at=_ts(day, 2, 50), warehouse_id="b", quantity=5),
        SnapshotStockPoint(captured_at=_ts(day, 15, 0), warehouse_id="a", quantity=99),
        SnapshotStockPoint(captured_at=_ts(day, 15, 0), warehouse_id="b", quantity=99),
    ]
    anchors = build_daily_stock_anchors(points, prefer_hour_utc=3)
    assert len(anchors) == 1
    assert anchors[0].total_quantity == 15
    assert anchors[0].captured_at.hour == 2


def test_window_filters_restock_and_sums_clean_sales() -> None:
    d0 = date(2026, 8, 1)
    anchors = [
        DailyStockAnchor(
            day=d0,
            captured_at=_ts(d0),
            total_quantity=100,
            warehouses=(WarehouseQuantity(warehouse_id="w", quantity=100),),
        ),
        DailyStockAnchor(
            day=d0 + timedelta(days=1),
            captured_at=_ts(d0 + timedelta(days=1)),
            total_quantity=90,  # sold 10
            warehouses=(WarehouseQuantity(warehouse_id="w", quantity=90),),
        ),
        DailyStockAnchor(
            day=d0 + timedelta(days=2),
            captured_at=_ts(d0 + timedelta(days=2)),
            total_quantity=190,  # restock +100
            warehouses=(WarehouseQuantity(warehouse_id="w", quantity=190),),
        ),
        DailyStockAnchor(
            day=d0 + timedelta(days=3),
            captured_at=_ts(d0 + timedelta(days=3)),
            total_quantity=180,  # sold 10
            warehouses=(WarehouseQuantity(warehouse_id="w", quantity=180),),
        ),
        DailyStockAnchor(
            day=d0 + timedelta(days=4),
            captured_at=_ts(d0 + timedelta(days=4)),
            total_quantity=182,  # return +2
            warehouses=(WarehouseQuantity(warehouse_id="w", quantity=182),),
        ),
    ]
    summary = estimate_sales_window(anchors, sku_id=uuid4())
    assert summary.total_units_sold == 20
    assert summary.total_units_returned == 2
    assert summary.total_units_restocked == 100
    assert summary.net_units == 18
    assert summary.last_24h is not None
    assert summary.last_24h.kind is StockMovementKind.RETURN


def test_snapshots_pipeline_end_to_end() -> None:
    sku = uuid4()
    d0 = date(2026, 8, 5)
    points = [
        SnapshotStockPoint(captured_at=_ts(d0), warehouse_id="w1", quantity=20),
        SnapshotStockPoint(captured_at=_ts(d0), warehouse_id="w2", quantity=10),
        SnapshotStockPoint(
            captured_at=_ts(d0 + timedelta(days=1)),
            warehouse_id="w1",
            quantity=15,
        ),
        SnapshotStockPoint(
            captured_at=_ts(d0 + timedelta(days=1)),
            warehouse_id="w2",
            quantity=10,
        ),
    ]
    summary = snapshots_to_sales_window(points, sku_id=sku)
    assert summary.sku_id == sku
    assert summary.total_units_sold == 5
    assert summary.last_24h is not None
    assert summary.last_24h.units_sold == 5


def test_config_rejects_overlapping_return_restock_bands() -> None:
    with pytest.raises(ValueError, match="restock_relative_min_units"):
        StockSalesFilterConfig(return_max_units=5, restock_relative_min_units=3)


def test_single_anchor_window_is_empty() -> None:
    day = date(2026, 8, 7)
    summary = estimate_sales_window(
        [
            DailyStockAnchor(
                day=day,
                captured_at=_ts(day),
                total_quantity=10,
                warehouses=(),
            )
        ]
    )
    assert summary.total_units_sold == 0
    assert summary.last_24h is None
    assert summary.skipped_day_count == 1
