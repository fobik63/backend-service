"""Unit tests for heuristic sales / GMV estimates (pre-MPSTATS)."""

from __future__ import annotations

from app.domain.estimated_sales import (
    DEFAULT_REVIEWS_TO_PURCHASES_RATIO,
    estimate_purchases,
    estimate_revenue_rub,
    estimate_sales,
)


def test_estimate_purchases_midpoint_ratio() -> None:
    assert estimate_purchases(100) == int(round(100 * DEFAULT_REVIEWS_TO_PURCHASES_RATIO))
    assert estimate_purchases(100) == 1250


def test_estimate_revenue_rub_basic() -> None:
    # 100 reviews × 12.5 = 1250 purchases × 499 ₽
    assert estimate_revenue_rub(feedbacks=100, price_rub=499.0) == 623_750.0


def test_estimate_revenue_rub_missing_inputs() -> None:
    assert estimate_revenue_rub(feedbacks=None, price_rub=499.0) is None
    assert estimate_revenue_rub(feedbacks=100, price_rub=None) is None
    assert estimate_purchases(None) is None


def test_estimate_sales_bundle() -> None:
    sales = estimate_sales(feedbacks=80, price_rub=350.0)
    assert sales is not None
    assert sales.feedbacks == 80
    assert sales.estimated_purchases == 1000
    assert sales.estimated_revenue_rub == 350_000.0
    assert sales.reviews_to_purchases_ratio == DEFAULT_REVIEWS_TO_PURCHASES_RATIO


def test_estimate_sales_custom_ratio_band() -> None:
    low = estimate_revenue_rub(
        feedbacks=10,
        price_rub=100.0,
        reviews_to_purchases_ratio=10.0,
    )
    high = estimate_revenue_rub(
        feedbacks=10,
        price_rub=100.0,
        reviews_to_purchases_ratio=15.0,
    )
    assert low == 10_000.0
    assert high == 15_000.0
