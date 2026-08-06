"""SQLAlchemy adapter for style-preset selection tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.style_analytics import NicheSelectionAggregate, StyleSelectionAggregate
from app.models.style_preset_selection import StylePresetSelection


class StyleAnalyticsRepository:
    """Persist and aggregate style-preset selection events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_selections(
        self,
        *,
        user_id: UUID | None,
        generation_job_id: UUID | None,
        niche_key: str,
        selections: Sequence[object],
    ) -> None:
        """Stage selection rows on the current session (no commit)."""

        normalized_niche = (niche_key or "generic").strip().lower()[:64] or "generic"
        for item in selections:
            slide_key = str(getattr(item, "slide_key", "") or "").strip()[:64]
            selected_style = str(getattr(item, "selected_style", "") or "").strip()[:500]
            if not slide_key or not selected_style:
                continue
            self._session.add(
                StylePresetSelection(
                    user_id=user_id,
                    generation_job_id=generation_job_id,
                    niche_key=normalized_niche,
                    slide_key=slide_key,
                    selected_style=selected_style,
                )
            )

    async def aggregate_styles_since(
        self,
        *,
        since: datetime,
        niche_key: str | None = None,
        limit: int = 50,
    ) -> list[StyleSelectionAggregate]:
        """Group selections by niche, slide, and style since ``since``."""

        stmt = (
            select(
                StylePresetSelection.niche_key,
                StylePresetSelection.slide_key,
                StylePresetSelection.selected_style,
                func.count().label("selection_count"),
            )
            .where(StylePresetSelection.created_at >= since)
            .group_by(
                StylePresetSelection.niche_key,
                StylePresetSelection.slide_key,
                StylePresetSelection.selected_style,
            )
            .order_by(func.count().desc())
            .limit(max(1, min(limit, 200)))
        )
        if niche_key:
            stmt = stmt.where(StylePresetSelection.niche_key == niche_key.strip().lower())

        rows = (await self._session.execute(stmt)).all()
        return [
            StyleSelectionAggregate(
                niche_key=str(row.niche_key),
                slide_key=str(row.slide_key),
                selected_style=str(row.selected_style),
                selection_count=int(row.selection_count),
            )
            for row in rows
        ]

    async def aggregate_niches_since(
        self,
        *,
        since: datetime,
    ) -> list[NicheSelectionAggregate]:
        """Group selections by niche since ``since``."""

        stmt = (
            select(
                StylePresetSelection.niche_key,
                func.count().label("selection_count"),
            )
            .where(StylePresetSelection.created_at >= since)
            .group_by(StylePresetSelection.niche_key)
            .order_by(func.count().desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            NicheSelectionAggregate(
                niche_key=str(row.niche_key),
                selection_count=int(row.selection_count),
            )
            for row in rows
        ]
