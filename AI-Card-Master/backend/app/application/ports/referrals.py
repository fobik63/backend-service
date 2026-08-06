"""Referral persistence port for application-level referral workflows."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class ReferralPersistencePort(Protocol):
    """Storage operations needed by referral use cases."""

    async def ensure_referral_code(self, user_id: UUID) -> str:
        """Return an existing code or create a unique one for the user."""

    async def get_user_id_by_referral_code(self, referral_code: str) -> UUID | None:
        """Resolve a referral code to its owner."""

    async def has_referrer(self, user_id: UUID) -> bool:
        """Whether the user already has an inviter assigned."""

    async def has_successful_payment(self, user_id: UUID) -> bool:
        """Whether the user has already paid before applying a referral."""

    async def assign_referrer(self, user_id: UUID, referrer_id: UUID) -> None:
        """Persist a user's inviter."""

    async def count_invited_users(self, referrer_id: UUID) -> int:
        """Count all users invited by the referrer."""

    async def count_paid_invited_users(self, referrer_id: UUID) -> int:
        """Count invited users whose referral bonus was already granted."""
