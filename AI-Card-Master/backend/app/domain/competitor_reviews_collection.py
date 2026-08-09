"""Collect low-rating (1–3★) competitor review complaint texts for later analysis."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.competitor_audit import MAX_REVIEWS_PER_CARD, CompetitorReview
from app.domain.competitors_search import MAX_COMPETITORS_LIMIT
from app.domain.eye_of_god_spy import DEFAULT_TOP_COMPETITORS

DEFAULT_COMPETITORS_FOR_REVIEWS = DEFAULT_TOP_COMPETITORS
MIN_ARTICLES = 1
MAX_ARTICLES = MAX_COMPETITORS_LIMIT
MAX_COMPLAINT_TEXT_LENGTH = 2000
# Aligned with pain-analysis ``raw_negative_reviews`` cap.
MAX_COMPLAINT_TEXTS = 100
LOW_RATING_MAX = 3


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompetitorReviewsCollectionRequest(StrictDomainModel):
    """TOP-N competitor articles (nm_id) whose 1–3★ reviews should be collected."""

    articles: list[str] = Field(
        min_length=MIN_ARTICLES,
        max_length=MAX_ARTICLES,
        description="Competitor nm_id list from TOP-10 search (1–10 articles).",
    )
    max_reviews_per_article: int = Field(
        default=MAX_REVIEWS_PER_CARD,
        ge=1,
        le=MAX_REVIEWS_PER_CARD,
        description="Max low-rating reviews to pull per competitor card.",
    )

    @field_validator("articles", mode="before")
    @classmethod
    def _normalize_articles(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("articles must be a list of nm_id strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, (str, int)):
                raise ValueError("Each article must be a string or int nm_id.")
            article = str(item).strip()
            if not article:
                continue
            if not article.isdigit():
                raise ValueError(f"Invalid Wildberries article (nm_id): {article!r}")
            if article in seen:
                continue
            seen.add(article)
            cleaned.append(article[:64])
        if not cleaned:
            raise ValueError("At least one valid competitor article is required.")
        return cleaned[:MAX_ARTICLES]


class CompetitorArticleReviews(StrictDomainModel):
    """Per-competitor low-rating review harvest summary."""

    article: str = Field(min_length=1, max_length=64)
    reviews_fetched: int = Field(ge=0, le=MAX_REVIEWS_PER_CARD)
    complaint_texts: list[str] = Field(default_factory=list, max_length=MAX_REVIEWS_PER_CARD)
    warning: str | None = Field(default=None, max_length=500)


class CompetitorReviewsCollectionResult(StrictDomainModel):
    """Unified complaint-text corpus from TOP-N competitors (1–3★ focus)."""

    articles: list[str] = Field(min_length=0, max_length=MAX_ARTICLES)
    competitors_processed: int = Field(ge=0, le=MAX_ARTICLES)
    reviews_fetched: int = Field(ge=0)
    complaint_texts: list[str] = Field(
        default_factory=list,
        max_length=MAX_COMPLAINT_TEXTS,
        description=(
            'Flat list of complaint strings for downstream analysis '
            '(e.g. "жидкий", "плохо пахнет", "сломана крышка").'
        ),
    )
    by_article: list[CompetitorArticleReviews] = Field(
        default_factory=list,
        max_length=MAX_ARTICLES,
    )
    warnings: list[str] = Field(default_factory=list, max_length=40)


def extract_complaint_texts(
    reviews: list[CompetitorReview],
    *,
    max_rating: int = LOW_RATING_MAX,
) -> list[str]:
    """Pull non-empty complaint strings from 1–3★ reviews (cons preferred, then body)."""

    texts: list[str] = []
    seen: set[str] = set()
    for review in reviews:
        if review.rating < 1 or review.rating > max_rating:
            continue
        candidate = _complaint_from_review(review)
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        texts.append(candidate)
    return texts


def _complaint_from_review(review: CompetitorReview) -> str | None:
    parts: list[str] = []
    cons = (review.cons or "").strip()
    body = (review.text or "").strip()
    if cons:
        parts.append(cons)
    if body and body.casefold() != cons.casefold():
        parts.append(body)
    if not parts:
        return None
    merged = re.sub(r"\s+", " ", " | ".join(parts)).strip()
    if not merged:
        return None
    return merged[:MAX_COMPLAINT_TEXT_LENGTH]


def merge_complaint_corpus(
    per_article: list[CompetitorArticleReviews],
    *,
    limit: int = MAX_COMPLAINT_TEXTS,
) -> list[str]:
    """Flatten + dedupe per-article complaint lists into one analysis corpus."""

    merged: list[str] = []
    seen: set[str] = set()
    for bucket in per_article:
        for text in bucket.complaint_texts:
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged
