"""Protocol for collecting low-rating Wildberries competitor reviews."""

from __future__ import annotations

from typing import Protocol

from app.domain.competitor_audit import CompetitorReview


class CompetitorLowRatingReviewsPort(Protocol):
    """Fetch 1–3★ reviews for a single competitor article (nm_id)."""

    async def fetch_low_rating_reviews(
        self,
        article: str,
        *,
        limit: int = 50,
    ) -> list[CompetitorReview]:
        """Return low-rating reviews for one Wildberries nm_id."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
