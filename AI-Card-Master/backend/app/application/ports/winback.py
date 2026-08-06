"""Ports for Churn Prevention / Win-back persistence and messaging."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.winback import (
    InactivityCandidate,
    StyleUpdateRecipient,
    WinbackOfferStatus,
    WinbackOfferType,
    WinbackOfferView,
    WinbackTrigger,
)


class WinbackPersistencePort(Protocol):
    """Storage operations for retention offers and activity signals."""

    async def touch_last_seen(self, user_id: UUID, *, now: datetime) -> None:
        """Update last_seen_at when the user is active in the product."""

    async def set_telegram_id(self, user_id: UUID, telegram_id: int) -> None:
        """Bind a Telegram chat id used for trigger messages."""

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        """Return linked Telegram chat id, if any."""

    async def get_active_offer(self, user_id: UUID) -> WinbackOfferView | None:
        """Return pending or active (unused discount) offer that is not expired."""

    async def get_offer_for_user(
        self, *, user_id: UUID, offer_id: UUID
    ) -> WinbackOfferView | None:
        """Load one offer owned by the user."""

    async def count_offers(self, user_id: UUID) -> int:
        """Total offers ever created for alternating offer-type selection."""

    async def create_offer(
        self,
        *,
        user_id: UUID,
        trigger: WinbackTrigger,
        offer_type: WinbackOfferType,
        title: str,
        message: str,
        free_generations: int | None,
        discount_percent: int | None,
        expires_at: datetime,
    ) -> WinbackOfferView:
        """Persist a new one-shot retention offer."""

    async def mark_offer_status(
        self,
        *,
        offer_id: UUID,
        status: WinbackOfferStatus,
        claimed_at: datetime | None = None,
    ) -> WinbackOfferView:
        """Transition offer lifecycle status."""

    async def credit_free_generations(self, *, user_id: UUID, coins: int) -> int:
        """Add AI-coins and return the new balance."""

    async def get_active_discount_percent(self, user_id: UUID) -> int | None:
        """Return discount percent for an ACTIVE subscription_discount offer."""

    async def get_active_discount_offer_id(self, user_id: UUID) -> UUID | None:
        """Return ACTIVE discount offer id for payment redemption."""

    async def redeem_discount_offer(self, *, user_id: UUID, offer_id: UUID) -> None:
        """Mark an ACTIVE discount offer as REDEEMED after successful payment."""

    async def favorite_style_for_user(self, user_id: UUID) -> str | None:
        """Most frequently selected style for the user, if any."""

    async def list_inactivity_candidates(
        self,
        *,
        inactive_before: datetime,
        limit: int,
    ) -> tuple[InactivityCandidate, ...]:
        """Users inactive long enough and without a usable open offer."""

    async def list_luxury_loft_recipients(
        self,
        *,
        campaign_key: str,
        limit: int,
    ) -> tuple[StyleUpdateRecipient, ...]:
        """Users whose favorite style is Luxury Loft and not yet notified."""

    async def mark_style_update_sent(
        self,
        *,
        user_id: UUID,
        style_key: str,
        campaign_key: str,
    ) -> None:
        """Record that a style-update Telegram was delivered."""

    async def expire_stale_offers(self, *, now: datetime) -> int:
        """Flip PENDING/ACTIVE offers past expires_at to EXPIRED."""
