"""BrandDNA application service — analyze winners and expose injectable context."""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.brand_dna import (
    BrandDNAPersistencePort,
    SuccessfulGenerationsPort,
)
from app.domain.brand_dna import (
    BrandDNAContext,
    BrandDNAStatus,
    BrandDNAView,
    analyze_successful_generations,
    build_claude_context,
    build_midjourney_context,
    context_from_view,
)

logger = logging.getLogger(__name__)


class BrandDNAService:
    """Coordinate BrandDNA refresh from successful generations + prompt lookup."""

    def __init__(
        self,
        persistence: BrandDNAPersistencePort,
        samples: SuccessfulGenerationsPort,
        *,
        sample_limit: int = 25,
        min_samples: int = 1,
        enabled: bool = True,
    ) -> None:
        self._persistence = persistence
        self._samples = samples
        self._sample_limit = max(1, sample_limit)
        self._min_samples = max(1, min_samples)
        self._enabled = enabled

    async def get(self, *, user_id: UUID) -> BrandDNAView | None:
        """Return the seller BrandDNA profile if it exists."""

        return await self._persistence.get_by_user_id(user_id)

    async def get_active_context(self, *, user_id: UUID) -> BrandDNAContext | None:
        """Return injectable Midjourney/Claude context when BrandDNA is active."""

        if not self._enabled:
            return None
        view = await self._persistence.get_active_for_user(user_id)
        if view is None:
            return None
        return context_from_view(view)

    async def set_active(self, *, user_id: UUID, is_active: bool) -> BrandDNAView | None:
        """Toggle automatic BrandDNA injection for the seller."""

        return await self._persistence.set_active(user_id=user_id, is_active=is_active)

    async def refresh_from_successful_generations(
        self,
        *,
        user_id: UUID,
    ) -> BrandDNAView | None:
        """Re-analyze completed generations and upsert BrandDNA context."""

        if not self._enabled:
            logger.info("BrandDNA disabled; skip refresh user_id=%s", user_id)
            return await self._persistence.get_by_user_id(user_id)

        await self._persistence.mark_analyzing(user_id)
        samples = await self._samples.list_successful_samples(
            user_id=user_id,
            limit=self._sample_limit,
        )
        if len(samples) < self._min_samples:
            logger.info(
                "BrandDNA refresh skipped — not enough successful gens user_id=%s count=%s",
                user_id,
                len(samples),
            )
            existing = await self._persistence.get_by_user_id(user_id)
            return existing

        signals = analyze_successful_generations(samples)
        if signals is None:
            logger.info(
                "BrandDNA refresh produced no signals user_id=%s",
                user_id,
            )
            return await self._persistence.get_by_user_id(user_id)

        view = await self._persistence.upsert_from_signals(
            user_id=user_id,
            signals=signals,
            midjourney_context=build_midjourney_context(signals),
            claude_context=build_claude_context(signals),
            status=BrandDNAStatus.READY,
            activate=True,
        )
        logger.info(
            "BrandDNA refreshed user_id=%s version=%s samples=%s styles=%s",
            user_id,
            view.version,
            view.sample_count,
            len(view.dominant_styles),
        )
        return view
