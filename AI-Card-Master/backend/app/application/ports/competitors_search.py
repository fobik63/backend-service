"""Protocol for Wildberries keyword competitor discovery."""

from __future__ import annotations

from typing import Protocol

from app.domain.eye_of_god_spy import CompetitorDiscoveryHit


class CompetitorKeywordDiscoveryPort(Protocol):
    """Search marketplace catalog by keyword and return ranked competitor hits."""

    async def discover_by_query(
        self,
        *,
        query: str,
        exclude_article: str | None = None,
        limit: int = 10,
    ) -> list[CompetitorDiscoveryHit]:
        """Return TOP-N competitor hits for a search query."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
