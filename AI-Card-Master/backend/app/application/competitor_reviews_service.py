"""Application service: TOP-N competitors → unified 1–3★ complaint text corpus."""

from __future__ import annotations

import asyncio
import logging

from app.application.ports.competitor_reviews import CompetitorLowRatingReviewsPort
from app.domain.competitor_audit import CompetitorReview
from app.domain.competitor_reviews_collection import (
    CompetitorArticleReviews,
    CompetitorReviewsCollectionRequest,
    CompetitorReviewsCollectionResult,
    extract_complaint_texts,
    merge_complaint_corpus,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)

logger = logging.getLogger(__name__)


class CompetitorReviewsError(Exception):
    """Base competitor-reviews collection failure."""


class CompetitorReviewsValidationError(CompetitorReviewsError):
    """Invalid articles or empty collection request."""


class CompetitorReviewsUpstreamError(CompetitorReviewsError):
    """Wildberries feedbacks API unavailable for all competitors."""


class CompetitorReviewsCollectionService:
    """Asynchronously harvest 1–3★ complaint texts from TOP-N competitor cards."""

    def __init__(self, reviews_client: CompetitorLowRatingReviewsPort) -> None:
        self._reviews = reviews_client

    async def collect_complaint_texts(
        self,
        request: CompetitorReviewsCollectionRequest,
    ) -> CompetitorReviewsCollectionResult:
        """Fetch low-rating reviews for each article and flatten into one string list.

        Concurrent ``asyncio.gather`` over TOP-N nm_ids. Per-article failures are
        recorded as warnings; only a total wipe-out raises ``UpstreamError``.
        """

        if not request.articles:
            raise CompetitorReviewsValidationError(
                "At least one competitor article is required."
            )

        gathered = await asyncio.gather(
            *[
                self._fetch_one(article, limit=request.max_reviews_per_article)
                for article in request.articles
            ],
            return_exceptions=True,
        )

        by_article: list[CompetitorArticleReviews] = []
        warnings: list[str] = []
        upstream_failures = 0

        for article, outcome in zip(request.articles, gathered, strict=True):
            if isinstance(outcome, BaseException):
                upstream_failures += 1
                message = _format_fetch_error(article, outcome)
                warnings.append(message)
                by_article.append(
                    CompetitorArticleReviews(
                        article=article,
                        reviews_fetched=0,
                        complaint_texts=[],
                        warning=message,
                    )
                )
                continue

            reviews, article_warning = outcome
            texts = extract_complaint_texts(reviews)
            if article_warning:
                warnings.append(article_warning)
            by_article.append(
                CompetitorArticleReviews(
                    article=article,
                    reviews_fetched=len(reviews),
                    complaint_texts=texts,
                    warning=article_warning,
                )
            )

        if upstream_failures == len(request.articles):
            raise CompetitorReviewsUpstreamError(
                "Wildberries feedbacks API is temporarily unavailable "
                "for all requested competitors."
            )

        complaint_texts = merge_complaint_corpus(by_article)
        return CompetitorReviewsCollectionResult(
            articles=list(request.articles),
            competitors_processed=len(request.articles) - upstream_failures,
            reviews_fetched=sum(item.reviews_fetched for item in by_article),
            complaint_texts=complaint_texts,
            by_article=by_article,
            warnings=warnings[:40],
        )

    async def _fetch_one(
        self,
        article: str,
        *,
        limit: int,
    ) -> tuple[list[CompetitorReview], str | None]:
        try:
            reviews = await self._reviews.fetch_low_rating_reviews(
                article,
                limit=limit,
            )
        except ParserSchemaError as exc:
            return [], f"article={article}: {exc}"
        except (ParserHttpError, ParserTransportError) as exc:
            logger.warning("WB reviews fetch failed for nm=%s: %s", article, exc)
            raise
        return reviews, None

    async def aclose(self) -> None:
        await self._reviews.aclose()


def _format_fetch_error(article: str, exc: BaseException) -> str:
    if isinstance(exc, (ParserHttpError, ParserTransportError, ParserSchemaError)):
        return f"article={article}: {exc}"
    return f"article={article}: unexpected error ({type(exc).__name__})"
