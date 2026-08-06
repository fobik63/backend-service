"""Application use cases for referrals."""

from __future__ import annotations

from uuid import UUID

from app.application.ports.referrals import ReferralPersistencePort
from app.domain.referral import ReferralStats, normalize_referral_code


class ReferralError(Exception):
    """Base referral workflow failure."""


class ReferralValidationError(ReferralError):
    """Referral request is invalid for the current user state."""


class ReferralNotFoundError(ReferralError):
    """Referral code owner was not found."""


class ReferralService:
    """Coordinate referral code ownership, application, and statistics."""

    def __init__(
        self,
        repository: ReferralPersistencePort,
        *,
        bonus_credits_per_friend: int,
    ) -> None:
        if bonus_credits_per_friend <= 0:
            raise ReferralValidationError("Referral bonus must be greater than zero.")
        self._repository = repository
        self._bonus_credits_per_friend = bonus_credits_per_friend

    async def get_stats(self, user_id: UUID) -> ReferralStats:
        """Return user's referral code and aggregate counters."""

        referral_code = await self._repository.ensure_referral_code(user_id)
        invited_count = await self._repository.count_invited_users(user_id)
        paid_invited_count = await self._repository.count_paid_invited_users(user_id)
        return ReferralStats(
            referral_code=referral_code,
            invited_count=invited_count,
            paid_invited_count=paid_invited_count,
            earned_free_credits=paid_invited_count * self._bonus_credits_per_friend,
            bonus_credits_per_friend=self._bonus_credits_per_friend,
        )

    async def apply_referral_code(self, *, user_id: UUID, referral_code: str) -> UUID:
        """Attach the current user to a referrer before their first payment."""

        normalized = normalize_referral_code(referral_code)
        if not normalized:
            raise ReferralValidationError("Referral code is required.")

        referrer_id = await self._repository.get_user_id_by_referral_code(normalized)
        if referrer_id is None:
            raise ReferralNotFoundError("Referral code not found.")
        if referrer_id == user_id:
            raise ReferralValidationError("Users cannot apply their own referral code.")
        if await self._repository.has_referrer(user_id):
            raise ReferralValidationError("Referral code is already applied.")
        if await self._repository.has_successful_payment(user_id):
            raise ReferralValidationError(
                "Referral code can only be applied before the first successful payment."
            )

        await self._repository.assign_referrer(user_id, referrer_id)
        return referrer_id
