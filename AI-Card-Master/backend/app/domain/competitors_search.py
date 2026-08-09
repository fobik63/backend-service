"""Keyword-based TOP-N Wildberries competitor discovery (search.wb.ru)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.estimated_sales import estimate_purchases, estimate_revenue_rub
from app.domain.eye_of_god_spy import (
    DEFAULT_TOP_COMPETITORS,
    MAX_TOP_COMPETITORS,
    CompetitorDiscoveryHit,
)

DEFAULT_COMPETITORS_LIMIT = DEFAULT_TOP_COMPETITORS
MIN_COMPETITORS_LIMIT = 1
MAX_COMPETITORS_LIMIT = MAX_TOP_COMPETITORS
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 256


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompetitorsSearchRequest(StrictDomainModel):
    """Search Wildberries catalog by keyword and return TOP-N competitor cards."""

    query: str = Field(
        min_length=MIN_QUERY_LENGTH,
        max_length=MAX_QUERY_LENGTH,
        description='Keyword query, e.g. "крем для рук увлажняющий".',
    )
    limit: int = Field(
        default=DEFAULT_COMPETITORS_LIMIT,
        ge=MIN_COMPETITORS_LIMIT,
        le=MAX_COMPETITORS_LIMIT,
        description="How many TOP competitors to return (default 10).",
    )

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


class CompetitorSearchCard(StrictDomainModel):
    """One competitor card from WB search SERP."""

    rank: int = Field(ge=1, le=MAX_COMPETITORS_LIMIT)
    article: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    brand: str | None = Field(default=None, max_length=256)
    price_rub: float | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    feedbacks: int | None = Field(default=None, ge=0)
    url: str = Field(min_length=12, max_length=2048)
    # Heuristic until MPSTATS/MarketGuru: feedbacks × ~12.5 × price.
    estimated_purchases: int | None = Field(default=None, ge=0)
    estimated_revenue_rub: float | None = Field(default=None, ge=0)


class CompetitorsSearchResult(StrictDomainModel):
    """TOP-N competitor cards for a keyword query."""

    query: str = Field(min_length=MIN_QUERY_LENGTH, max_length=MAX_QUERY_LENGTH)
    count: int = Field(ge=0, le=MAX_COMPETITORS_LIMIT)
    competitors: list[CompetitorSearchCard] = Field(default_factory=list)


def hits_to_search_result(
    *,
    query: str,
    hits: list[CompetitorDiscoveryHit],
) -> CompetitorsSearchResult:
    """Map discovery hits to the public competitors-search DTO."""

    cards = [
        CompetitorSearchCard(
            rank=hit.rank,
            article=hit.article,
            title=hit.title,
            brand=hit.brand,
            price_rub=hit.price_rub,
            rating=hit.rating,
            feedbacks=hit.feedbacks,
            url=hit.url,
            estimated_purchases=estimate_purchases(hit.feedbacks),
            estimated_revenue_rub=estimate_revenue_rub(
                feedbacks=hit.feedbacks,
                price_rub=hit.price_rub,
            ),
        )
        for hit in hits
    ]
    return CompetitorsSearchResult(query=query, count=len(cards), competitors=cards)
