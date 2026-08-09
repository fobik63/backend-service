"""Ports for the inbound Telegram bot (commands + account link)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.telegram_bot import TelegramUserStatus


class TelegramBotUserPort(Protocol):
    async def get_status_by_telegram_id(self, telegram_id: int) -> TelegramUserStatus | None:
        """Return subscription/balance for a linked Telegram chat."""

    async def get_status_by_user_id(self, user_id: UUID) -> TelegramUserStatus | None:
        """Return subscription/balance for an account id."""

    async def link_telegram(self, *, user_id: UUID, telegram_id: int) -> TelegramUserStatus:
        """Bind telegram chat id to the user account."""

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        """Return linked chat id when present."""


class TelegramOutboundPort(Protocol):
    async def send_message(self, *, chat_id: int, text: str) -> bool:
        """Send a plain-text reply to a chat."""
