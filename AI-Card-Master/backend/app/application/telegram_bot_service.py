"""Use cases: Telegram /start deep-link binding and /status."""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.telegram_bot import TelegramBotUserPort, TelegramOutboundPort
from app.domain.telegram_bot import (
    TelegramBotNotFoundError,
    TelegramBotValidationError,
    TelegramUpdateCommand,
    build_deep_link_payload,
    message_start_linked,
    message_start_need_link,
    message_status,
    message_unlinked,
    parse_deep_link_payload,
)

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Handle inbound bot commands without depending on FastAPI/httpx."""

    def __init__(
        self,
        users: TelegramBotUserPort,
        outbound: TelegramOutboundPort,
        *,
        signing_secret: str,
        bot_username: str = "",
        deep_link_ttl_seconds: int = 3_600,
    ) -> None:
        self._users = users
        self._outbound = outbound
        self._signing_secret = signing_secret
        self._bot_username = bot_username
        self._deep_link_ttl_seconds = deep_link_ttl_seconds

    def create_deep_link_payload(self, user_id: UUID) -> str:
        return build_deep_link_payload(
            user_id,
            secret=self._signing_secret,
            ttl_seconds=self._deep_link_ttl_seconds,
        )

    def deep_link_url(self, user_id: UUID) -> str | None:
        username = self._bot_username.lstrip("@").strip()
        if not username:
            return None
        payload = self.create_deep_link_payload(user_id)
        return f"https://t.me/{username}?start={payload}"

    async def handle_update_command(self, command: TelegramUpdateCommand) -> None:
        name = (command.command or "").lower()
        if name in {"start", "/start"}:
            await self._handle_start(command)
            return
        if name in {"status", "/status"}:
            await self._handle_status(command)
            return
        await self._outbound.send_message(
            chat_id=command.chat_id,
            text="Доступные команды: /start, /status",
        )

    async def notify_user(self, *, user_id: UUID, text: str) -> bool:
        chat_id = await self._users.get_telegram_id(user_id)
        if chat_id is None:
            return False
        return await self._outbound.send_message(chat_id=chat_id, text=text)

    async def _handle_start(self, command: TelegramUpdateCommand) -> None:
        args = (command.args or "").strip()
        if not args:
            existing = await self._users.get_status_by_telegram_id(command.telegram_user_id)
            if existing is not None:
                await self._outbound.send_message(
                    chat_id=command.chat_id,
                    text=message_start_linked(),
                )
                return
            await self._outbound.send_message(
                chat_id=command.chat_id,
                text=message_start_need_link(bot_username=self._bot_username),
            )
            return

        try:
            user_id = parse_deep_link_payload(args, secret=self._signing_secret)
            await self._users.link_telegram(
                user_id=user_id,
                telegram_id=command.telegram_user_id,
            )
        except TelegramBotValidationError as exc:
            await self._outbound.send_message(chat_id=command.chat_id, text=str(exc))
            return
        except TelegramBotNotFoundError as exc:
            await self._outbound.send_message(chat_id=command.chat_id, text=str(exc))
            return
        except Exception:
            logger.exception("Telegram /start link failed chat_id=%s", command.chat_id)
            await self._outbound.send_message(
                chat_id=command.chat_id,
                text="Не удалось привязать аккаунт. Попробуйте позже.",
            )
            return

        await self._outbound.send_message(
            chat_id=command.chat_id,
            text=message_start_linked(),
        )

    async def _handle_status(self, command: TelegramUpdateCommand) -> None:
        status = await self._users.get_status_by_telegram_id(command.telegram_user_id)
        if status is None:
            await self._outbound.send_message(
                chat_id=command.chat_id,
                text=message_unlinked(),
            )
            return
        await self._outbound.send_message(
            chat_id=command.chat_id,
            text=message_status(status),
        )
