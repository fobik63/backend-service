"""Ports for BrandDNA persistence and successful-generation sampling (plan §58)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.brand_dna import (
    BrandDNASignals,
    BrandDNAStatus,
    BrandDNAView,
    SuccessfulGenerationSample,
)


class BrandDNAPersistencePort(Protocol):
    """Store and load per-seller BrandDNA profiles."""

    async def get_by_user_id(self, user_id: UUID) -> BrandDNAView | None:
        """Return the BrandDNA row for a seller, if any."""

    async def get_active_for_user(self, user_id: UUID) -> BrandDNAView | None:
        """Return the active BrandDNA ready for prompt injection."""

    async def upsert_from_signals(
        self,
        *,
        user_id: UUID,
        signals: BrandDNASignals,
        midjourney_context: str,
        claude_context: str,
        status: BrandDNAStatus = BrandDNAStatus.READY,
        activate: bool = True,
    ) -> BrandDNAView:
        """Create or refresh BrandDNA from analyzed successful generations."""

    async def mark_analyzing(self, user_id: UUID) -> BrandDNAView | None:
        """Flip status to analyzing while a refresh job runs."""

    async def set_active(self, *, user_id: UUID, is_active: bool) -> BrandDNAView | None:
        """Enable or disable automatic BrandDNA injection for the seller."""


class SuccessfulGenerationsPort(Protocol):
    """Read completed seller generations used as BrandDNA training material."""

    async def list_successful_samples(
        self,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[SuccessfulGenerationSample, ...]:
        """Return newest completed generation jobs with slide styles/prompts."""
