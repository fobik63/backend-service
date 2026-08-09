"""SQLAlchemy referral persistence adapter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.referral import generate_referral_code
from app.models.enums import PaymentStatus
from app.models.payment import Payment
from app.models.user import User


class ReferralRepository:
    """Persist referral code ownership and invite counters."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_referral_code(self, user_id: UUID) -> str:
        """Return an existing code or create a unique one for the user."""

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise ValueError(f"User {user_id} not found.")
        if user.referral_code:
            return user.referral_code

        for _ in range(16):
            code = generate_referral_code()
            existing_id = await self.get_user_id_by_referral_code(code)
            if existing_id is not None:
                continue

            user.referral_code = code
            try:
                await self._session.commit()
            except IntegrityError as exc:
                await self._session.rollback()
                user = await self._session.get(User, user_id, with_for_update=True)
                if user is None:
                    raise ValueError(f"User {user_id} not found.") from exc
                if user.referral_code:
                    return user.referral_code
                continue
            await self._session.refresh(user)
            return user.referral_code

        raise RuntimeError("Unable to generate a unique referral code.")

    async def get_user_id_by_referral_code(self, referral_code: str) -> UUID | None:
        """Resolve a referral code to its owner."""

        return await self._session.scalar(
            select(User.id).where(User.referral_code == referral_code)
        )

    async def has_referrer(self, user_id: UUID) -> bool:
        """Whether the user already has an inviter assigned."""

        referrer_id = await self._session.scalar(
            select(User.referred_by_user_id).where(User.id == user_id)
        )
        return referrer_id is not None

    async def has_successful_payment(self, user_id: UUID) -> bool:
        """Whether the user has already completed any payment."""

        payment_id = await self._session.scalar(
            select(Payment.id)
            .where(Payment.user_id == user_id, Payment.status == PaymentStatus.SUCCEEDED)
            .limit(1)
        )
        return payment_id is not None

    async def assign_referrer(self, user_id: UUID, referrer_id: UUID) -> None:
        """Persist a user's inviter."""

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise ValueError(f"User {user_id} not found.")
        user.referred_by_user_id = referrer_id
        await self._session.commit()

    async def count_invited_users(self, referrer_id: UUID) -> int:
        """Count all users invited by the referrer."""

        count = await self._session.scalar(
            select(func.count()).select_from(User).where(User.referred_by_user_id == referrer_id)
        )
        return int(count or 0)

    async def count_paid_invited_users(self, referrer_id: UUID) -> int:
        """Count invited users whose bonus was already granted."""

        count = await self._session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.referred_by_user_id == referrer_id,
                User.referral_bonus_granted_at.is_not(None),
            )
        )
        return int(count or 0)
