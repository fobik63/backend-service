"""Persistence port for style-preset selection tracking and analytics."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence
from uuid import UUID

from app.domain.style_analytics import NicheSelectionAggregate, StyleSelectionAggregate


class StyleSelectionRecord(Protocol):
    """One style choice to persist atomically with a generation job."""

    slide_key: str
    selected_style: str


class StyleAnalyticsPersistencePort(Protocol):
    """Storage operations for internal style-preset tracking."""

    async def log_selections(
        self,
        *,
        user_id: UUID | None,
        generation_job_id: UUID | None,
        niche_key: str,
        selections: Sequence[StyleSelectionRecord],
    ) -> None:
        """Append selection events (caller owns the transaction/commit)."""

    async def aggregate_styles_since(
        self,
        *,
        since: datetime,
        niche_key: str | None = None,
        limit: int = 50,
    ) -> list[StyleSelectionAggregate]:
        """Return popular niche+slide+style triples ordered by count DESC."""

    async def aggregate_niches_since(
        self,
        *,
        since: datetime,
    ) -> list[NicheSelectionAggregate]:
        """Return niche popularity ordered by count DESC."""
