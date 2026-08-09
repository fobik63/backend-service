"""Heuristic sales / GMV estimates until MPSTATS / MarketGuru APIs are available.

WB search SERP exposes review counts (`feedbacks`) and price, but not true sales.
Marketplace practice: roughly 1 public review ≈ 10–15 paid orders (выкупы).
Estimated revenue ≈ feedbacks × ratio × current price.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Midpoint of the common 10–15 «выкупов на 1 отзыв» band.
DEFAULT_REVIEWS_TO_PURCHASES_RATIO = 12.5
MIN_REVIEWS_TO_PURCHASES_RATIO = 10.0
MAX_REVIEWS_TO_PURCHASES_RATIO = 15.0


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EstimatedSales(StrictDomainModel):
    """Approximate purchase volume and GMV derived from SERP feedbacks × price."""

    feedbacks: int = Field(ge=0)
    price_rub: float = Field(ge=0)
    reviews_to_purchases_ratio: float = Field(
        default=DEFAULT_REVIEWS_TO_PURCHASES_RATIO,
        ge=MIN_REVIEWS_TO_PURCHASES_RATIO,
        le=MAX_REVIEWS_TO_PURCHASES_RATIO,
    )
    estimated_purchases: int = Field(ge=0)
    estimated_revenue_rub: float = Field(ge=0)


def estimate_purchases(
    feedbacks: int | None,
    *,
    reviews_to_purchases_ratio: float = DEFAULT_REVIEWS_TO_PURCHASES_RATIO,
) -> int | None:
    """Approximate paid orders from public review count."""

    if feedbacks is None or feedbacks < 0:
        return None
    if reviews_to_purchases_ratio <= 0:
        return None
    return int(round(feedbacks * reviews_to_purchases_ratio))


def estimate_revenue_rub(
    *,
    feedbacks: int | None,
    price_rub: float | None,
    reviews_to_purchases_ratio: float = DEFAULT_REVIEWS_TO_PURCHASES_RATIO,
) -> float | None:
    """Approximate GMV (RUB): reviews × ratio × current card price."""

    purchases = estimate_purchases(
        feedbacks,
        reviews_to_purchases_ratio=reviews_to_purchases_ratio,
    )
    if purchases is None or price_rub is None or price_rub < 0:
        return None
    return round(purchases * float(price_rub), 2)


def estimate_sales(
    *,
    feedbacks: int | None,
    price_rub: float | None,
    reviews_to_purchases_ratio: float = DEFAULT_REVIEWS_TO_PURCHASES_RATIO,
) -> EstimatedSales | None:
    """Full heuristic bundle, or None when SERP inputs are missing."""

    purchases = estimate_purchases(
        feedbacks,
        reviews_to_purchases_ratio=reviews_to_purchases_ratio,
    )
    revenue = estimate_revenue_rub(
        feedbacks=feedbacks,
        price_rub=price_rub,
        reviews_to_purchases_ratio=reviews_to_purchases_ratio,
    )
    if (
        feedbacks is None
        or price_rub is None
        or purchases is None
        or revenue is None
        or feedbacks < 0
        or price_rub < 0
    ):
        return None
    return EstimatedSales(
        feedbacks=feedbacks,
        price_rub=float(price_rub),
        reviews_to_purchases_ratio=reviews_to_purchases_ratio,
        estimated_purchases=purchases,
        estimated_revenue_rub=revenue,
    )
