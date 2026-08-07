"""SQLAlchemy adapter for auth register/login."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.referral import generate_referral_code
from app.models.enums import SubscriptionStatus
from app.models.user import User


class AuthRepository:
    """Persist and look up users for authentication use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.scalar(select(User).where(User.email == email))
        return result

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        fingerprint_hash: str | None = None,
    ) -> User:
        normalized_fp = (fingerprint_hash or "").strip() or None
        if normalized_fp is not None:
            normalized_fp = normalized_fp[:64]
        user = User(
            email=email,
            hashed_password=hashed_password,
            subscription_status=SubscriptionStatus.FREE,
            ai_coins=0,
            referral_code=generate_referral_code(),
            fingerprint_hash=normalized_fp,
        )
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def update_fingerprint_hash(
        self,
        user_id: UUID,
        *,
        fingerprint_hash: str,
    ) -> User | None:
        normalized = (fingerprint_hash or "").strip()[:64]
        if not normalized:
            return await self.get_by_id(user_id)
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        if user.fingerprint_hash != normalized:
            user.fingerprint_hash = normalized
            await self._session.commit()
            await self._session.refresh(user)
        return user

    async def exists_fingerprint_hash(
        self,
        *,
        fingerprint_hash: str,
        exclude_user_id: UUID | None = None,
    ) -> bool:
        normalized = (fingerprint_hash or "").strip()
        if not normalized:
            return False
        stmt = select(User.id).where(User.fingerprint_hash == normalized[:64])
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        result = await self._session.scalar(stmt.limit(1))
        return result is not None

    async def flag_user(self, user_id: UUID, *, reason: str) -> User | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.is_flagged = True
        user.flag_reason = (reason or "")[:64] or None
        await self._session.commit()
        await self._session.refresh(user)
        return user
