"""SQLAlchemy adapter for Telegram bot user lookups and linking."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.telegram_bot import TelegramBotNotFoundError, TelegramUserStatus
from app.models.user import User


def _to_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


def _status_from_user(user: User) -> TelegramUserStatus:
    return TelegramUserStatus(
        user_id=user.id,
        telegram_id=user.telegram_id,
        subscription_status=str(user.subscription_status.value),
        subscription_ends_at=_to_utc_iso(user.subscription_ends_at),
        ai_coins=int(user.ai_coins),
    )


class TelegramBotUserRepository:
    """Persistence for Telegram account linking and /status."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_status_by_telegram_id(self, telegram_id: int) -> TelegramUserStatus | None:
        user = await self._session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        if user is None:
            return None
        return _status_from_user(user)

    async def get_status_by_user_id(self, user_id: UUID) -> TelegramUserStatus | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        return _status_from_user(user)

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        return user.telegram_id

    async def link_telegram(self, *, user_id: UUID, telegram_id: int) -> TelegramUserStatus:
        if telegram_id == 0:
            raise TelegramBotNotFoundError("Некорректный Telegram chat id.")

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise TelegramBotNotFoundError("Пользователь не найден.")

        conflict = await self._session.scalar(
            select(User.id).where(
                User.telegram_id == telegram_id,
                User.id != user_id,
            )
        )
        if conflict is not None:
            raise TelegramBotNotFoundError(
                "Этот Telegram уже привязан к другому аккаунту."
            )

        user.telegram_id = telegram_id
        await self._session.commit()
        await self._session.refresh(user)
        return _status_from_user(user)
