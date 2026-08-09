"""Unit tests for TOP-N competitor low-rating reviews collection."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.competitor_reviews_service import (
    CompetitorReviewsCollectionService,
    CompetitorReviewsUpstreamError,
)
from app.domain.competitor_audit import CompetitorReview
from app.domain.competitor_reviews_collection import (
    CompetitorReviewsCollectionRequest,
    extract_complaint_texts,
    merge_complaint_corpus,
    CompetitorArticleReviews,
)
from app.domain.stock_parser import ParserErrorKind, ParserMarketplace
from app.infrastructure.competitor_audit.wb_deep_client import (
    WildberriesDeepClient,
    _map_wb_feedbacks,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserTransportError,
)


class _FakeReviewsClient:
    def __init__(
        self,
        by_article: dict[str, list[CompetitorReview]] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._by_article = by_article or {}
        self._errors = errors or {}
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def fetch_low_rating_reviews(
        self,
        article: str,
        *,
        limit: int = 50,
    ) -> list[CompetitorReview]:
        self.calls.append({"article": article, "limit": limit})
        if article in self._errors:
            raise self._errors[article]
        return list(self._by_article.get(article, []))[:limit]

    async def aclose(self) -> None:
        self.closed = True


def _review(rating: int, text: str, *, cons: str | None = None) -> CompetitorReview:
    return CompetitorReview(rating=rating, text=text, cons=cons)


def test_extract_complaint_texts_prefers_cons_and_skips_high_rating() -> None:
    reviews = [
        _review(5, "отлично"),
        _review(2, "плохо пахнет", cons="жидкий"),
        _review(1, "сломана крышка"),
        _review(3, "   "),
    ]
    texts = extract_complaint_texts(reviews)
    assert texts == ["жидкий | плохо пахнет", "сломана крышка"]


def test_merge_complaint_corpus_dedupes() -> None:
    buckets = [
        CompetitorArticleReviews(
            article="1",
            reviews_fetched=2,
            complaint_texts=["жидкий", "плохо пахнет"],
        ),
        CompetitorArticleReviews(
            article="2",
            reviews_fetched=1,
            complaint_texts=["Жидкий", "сломана крышка"],
        ),
    ]
    merged = merge_complaint_corpus(buckets)
    assert merged == ["жидкий", "плохо пахнет", "сломана крышка"]


def test_request_normalizes_and_dedupes_articles() -> None:
    req = CompetitorReviewsCollectionRequest(articles=[" 111 ", 222, "111", "333"])
    assert req.articles == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_service_collects_flat_complaint_corpus() -> None:
    client = _FakeReviewsClient(
        {
            "1001": [
                _review(2, "плохо пахнет"),
                _review(1, "жидкий"),
            ],
            "1002": [
                _review(3, "сломана крышка"),
            ],
        }
    )
    service = CompetitorReviewsCollectionService(client)

    result = await service.collect_complaint_texts(
        CompetitorReviewsCollectionRequest(articles=["1001", "1002"])
    )

    assert result.competitors_processed == 2
    assert result.reviews_fetched == 3
    assert result.complaint_texts == ["плохо пахнет", "жидкий", "сломана крышка"]
    assert len(client.calls) == 2
    assert {c["article"] for c in client.calls} == {"1001", "1002"}


@pytest.mark.asyncio
async def test_service_partial_failure_keeps_successful_articles() -> None:
    client = _FakeReviewsClient(
        {"1001": [_review(1, "жидкий")]},
        errors={
            "1002": ParserTransportError(
                "timeout",
                marketplace=ParserMarketplace.WILDBERRIES,
            )
        },
    )
    service = CompetitorReviewsCollectionService(client)

    result = await service.collect_complaint_texts(
        CompetitorReviewsCollectionRequest(articles=["1001", "1002"])
    )

    assert result.competitors_processed == 1
    assert result.complaint_texts == ["жидкий"]
    assert any("1002" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_service_all_failures_raise_upstream() -> None:
    client = _FakeReviewsClient(
        errors={
            "1001": ParserHttpError(
                "blocked",
                marketplace=ParserMarketplace.WILDBERRIES,
                status_code=403,
                kind=ParserErrorKind.HTTP_403,
            ),
            "1002": ParserTransportError(
                "timeout",
                marketplace=ParserMarketplace.WILDBERRIES,
            ),
        }
    )
    service = CompetitorReviewsCollectionService(client)

    with pytest.raises(CompetitorReviewsUpstreamError):
        await service.collect_complaint_texts(
            CompetitorReviewsCollectionRequest(articles=["1001", "1002"])
        )


@pytest.mark.asyncio
async def test_wb_client_filters_to_low_rating_only() -> None:
    class _Transport:
        async def get_json(
            self, url: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            if "cards/v1/detail" in url:
                return {
                    "data": {
                        "products": [
                            {
                                "id": 123,
                                "name": "Крем",
                                "root": 999,
                                "salePriceU": 10000,
                            }
                        ]
                    }
                }
            assert "feedbacks" in url
            return {
                "feedbacks": [
                    {"id": 1, "productValuation": 5, "text": "супер"},
                    {
                        "id": 2,
                        "productValuation": 2,
                        "text": "плохо пахнет",
                        "cons": "жидкий",
                    },
                    {"id": 3, "productValuation": 1, "text": "сломана крышка"},
                ]
            }

        async def aclose(self) -> None:
            return None

    client = WildberriesDeepClient(transport=_Transport())  # type: ignore[arg-type]
    reviews = await client.fetch_low_rating_reviews("123", limit=50)

    assert len(reviews) == 2
    assert all(r.rating <= 3 for r in reviews)
    assert reviews[0].text == "плохо пахнет"
    assert reviews[0].cons == "жидкий"
    assert reviews[1].text == "сломана крышка"


def test_map_wb_feedbacks_max_rating_filter() -> None:
    payload = {
        "feedbacks": [
            {"id": 1, "productValuation": 4, "text": "ok"},
            {"id": 2, "productValuation": 2, "text": "жидкий"},
        ]
    }
    all_reviews = _map_wb_feedbacks(payload, limit=10)
    low_only = _map_wb_feedbacks(payload, limit=10, max_rating=3)
    assert len(all_reviews) == 2
    assert len(low_only) == 1
    assert low_only[0].text == "жидкий"
