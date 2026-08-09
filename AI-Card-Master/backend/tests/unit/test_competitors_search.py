"""Unit tests for keyword competitor search (WB search.wb.ru TOP-N)."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.competitors_search_service import (
    CompetitorsSearchService,
    CompetitorsSearchUpstreamError,
    CompetitorsSearchValidationError,
)
from app.domain.competitor_audit import CompetitorMarketplace
from app.domain.competitors_search import (
    CompetitorsSearchRequest,
    hits_to_search_result,
)
from app.domain.eye_of_god_spy import CompetitorDiscoveryHit
from app.domain.stock_parser import ParserErrorKind, ParserMarketplace
from app.infrastructure.competitor_audit.wb_discovery_client import (
    WildberriesCompetitorDiscovery,
    _extract_products,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)

class _FakeDiscovery:
    def __init__(self, hits: list[CompetitorDiscoveryHit] | None = None, *, error: Exception | None = None) -> None:
        self._hits = hits or []
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def discover_by_query(
        self,
        *,
        query: str,
        exclude_article: str | None = None,
        limit: int = 10,
    ) -> list[CompetitorDiscoveryHit]:
        self.calls.append(
            {"query": query, "exclude_article": exclude_article, "limit": limit}
        )
        if self._error is not None:
            raise self._error
        return self._hits[:limit]

    async def aclose(self) -> None:
        self.closed = True


def _hit(rank: int, article: str, *, price: float = 499.0) -> CompetitorDiscoveryHit:
    return CompetitorDiscoveryHit(
        rank=rank,
        article=article,
        url=f"https://www.wildberries.ru/catalog/{article}/detail.aspx",
        marketplace=CompetitorMarketplace.WILDBERRIES,
        title=f"Товар {article}",
        brand="Brand",
        price_rub=price,
        rating=4.8,
        feedbacks=1200 + rank,
    )


def test_hits_to_search_result_maps_fields() -> None:
    hits = [_hit(1, "111"), _hit(2, "222", price=590.0)]
    result = hits_to_search_result(query="крем для рук увлажняющий", hits=hits)
    assert result.query == "крем для рук увлажняющий"
    assert result.count == 2
    assert result.competitors[0].article == "111"
    assert result.competitors[0].price_rub == 499.0
    assert result.competitors[0].rating == 4.8
    assert result.competitors[0].feedbacks == 1201
    # 1201 × 12.5 × 499
    assert result.competitors[0].estimated_purchases == 15012
    assert result.competitors[0].estimated_revenue_rub == round(15012 * 499.0, 2)
    assert result.competitors[1].article == "222"
    assert result.competitors[1].estimated_purchases == 15025
    assert result.competitors[1].estimated_revenue_rub == round(15025 * 590.0, 2)


def test_competitors_search_request_normalizes_whitespace() -> None:
    req = CompetitorsSearchRequest(query="  крем   для рук  ")
    assert req.query == "крем для рук"
    assert req.limit == 10


@pytest.mark.asyncio
async def test_service_returns_top_n() -> None:
    hits = [_hit(i, str(1000 + i)) for i in range(1, 11)]
    discovery = _FakeDiscovery(hits)
    service = CompetitorsSearchService(discovery)

    result = await service.search(
        CompetitorsSearchRequest(query="крем для рук увлажняющий", limit=10)
    )

    assert result.count == 10
    assert len(result.competitors) == 10
    assert discovery.calls[0]["limit"] == 10
    assert result.competitors[0].article == "1001"


@pytest.mark.asyncio
async def test_service_maps_schema_error() -> None:
    discovery = _FakeDiscovery(
        error=ParserSchemaError(
            "No competitor products found for query",
            marketplace=ParserMarketplace.WILDBERRIES,
        )
    )
    service = CompetitorsSearchService(discovery)

    with pytest.raises(CompetitorsSearchValidationError):
        await service.search(CompetitorsSearchRequest(query="несуществующий товар xyz"))


@pytest.mark.asyncio
async def test_service_maps_transport_error() -> None:
    discovery = _FakeDiscovery(
        error=ParserTransportError(
            "timeout",
            marketplace=ParserMarketplace.WILDBERRIES,
        )
    )
    service = CompetitorsSearchService(discovery)

    with pytest.raises(CompetitorsSearchUpstreamError):
        await service.search(CompetitorsSearchRequest(query="крем для рук"))


@pytest.mark.asyncio
async def test_wb_discovery_parses_search_payload() -> None:
    class _Transport:
        async def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            assert "v7/search" in url
            assert params is not None
            assert params["query"] == "крем для рук увлажняющий"
            return {
                "data": {
                    "products": [
                        {
                            "id": 12345678,
                            "name": "Крем для рук увлажняющий",
                            "brand": "Nivea",
                            "salePriceU": 49900,
                            "reviewRating": 4.7,
                            "feedbacks": 3200,
                        },
                        {
                            "nmId": 87654321,
                            "name": "Крем для рук",
                            "brandName": "Other",
                            "priceU": 35000,
                            "rating": 4.2,
                            "nmFeedbacks": 800,
                        },
                    ]
                }
            }

        async def aclose(self) -> None:
            return None

    client = WildberriesCompetitorDiscovery(transport=_Transport())  # type: ignore[arg-type]
    hits = await client.discover_by_query(query="крем для рук увлажняющий", limit=10)

    assert len(hits) == 2
    assert hits[0].article == "12345678"
    assert hits[0].price_rub == 499.0
    assert hits[0].rating == 4.7
    assert hits[0].feedbacks == 3200
    assert hits[1].article == "87654321"
    assert hits[1].price_rub == 350.0


@pytest.mark.asyncio
async def test_wb_discovery_falls_back_to_v4() -> None:
    class _Transport:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.urls.append(url)
            if "v7" in url or "v5" in url:
                raise ParserHttpError(
                    "blocked",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    status_code=403,
                    kind=ParserErrorKind.HTTP_403,
                )
            return {
                "data": {
                    "products": [
                        {
                            "id": 111,
                            "name": "A",
                            "salePriceU": 10000,
                            "reviewRating": 5.0,
                            "feedbacks": 10,
                        }
                    ]
                }
            }

        async def aclose(self) -> None:
            return None

    transport = _Transport()
    client = WildberriesCompetitorDiscovery(transport=transport)  # type: ignore[arg-type]
    hits = await client.discover_by_query(query="крем", limit=1)

    assert len(hits) == 1
    assert any("v4/search" in u for u in transport.urls)
    assert hits[0].article == "111"


def test_extract_products_empty() -> None:
    assert _extract_products({}) == []
    assert _extract_products({"data": {}}) == []
