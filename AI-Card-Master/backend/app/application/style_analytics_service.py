"""Application use cases for style-preset tracking analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.ports.style_analytics import StyleAnalyticsPersistencePort
from app.domain.style_analytics import StylePresetAnalytics, build_style_preset_analytics


class StyleAnalyticsValidationError(Exception):
    """Invalid analytics query parameters."""


class StyleAnalyticsService:
    """Aggregate internal style usage and produce AI insight payloads."""

    def __init__(
        self,
        repository: StyleAnalyticsPersistencePort,
        *,
        niche_titles: dict[str, str] | None = None,
    ) -> None:
        self._repository = repository
        self._niche_titles = dict(niche_titles or {})

    async def get_preset_analytics(
        self,
        *,
        period_days: int = 30,
        niche_key: str | None = None,
        top_limit: int = 10,
    ) -> StylePresetAnalytics:
        """Return popularity ranking plus AI CTR/conversion insights."""

        if period_days < 1 or period_days > 365:
            raise StyleAnalyticsValidationError("period_days must be between 1 and 365.")
        if top_limit < 1 or top_limit > 50:
            raise StyleAnalyticsValidationError("top_limit must be between 1 and 50.")

        normalized_niche = niche_key.strip().lower() if niche_key else None
        since = datetime.now(UTC) - timedelta(days=period_days)
        style_rows = await self._repository.aggregate_styles_since(
            since=since,
            niche_key=normalized_niche,
            limit=max(top_limit * 5, 50),
        )
        niche_rows = await self._repository.aggregate_niches_since(since=since)
        if normalized_niche is not None:
            niche_rows = [row for row in niche_rows if row.niche_key == normalized_niche]

        return build_style_preset_analytics(
            generated_at=datetime.now(UTC),
            period_days=period_days,
            style_rows=style_rows,
            niche_rows=niche_rows,
            niche_titles=self._niche_titles,
            top_limit=top_limit,
        )


def load_niche_titles_from_catalog(catalog: dict[str, Any] | None) -> dict[str, str]:
    """Extract niche_key → title from style_presets catalog dump."""

    if not catalog:
        return {}
    niches = catalog.get("niches") or {}
    titles: dict[str, str] = {}
    if not isinstance(niches, dict):
        return titles
    for key, value in niches.items():
        if isinstance(value, dict):
            title = value.get("title")
            if isinstance(title, str) and title.strip():
                titles[str(key)] = title.strip()
    return titles
