"""Parse Telegram Update payloads into domain commands."""

from __future__ import annotations

from typing import Any

from app.domain.telegram_bot import TelegramUpdateCommand


def extract_bot_command(update: dict[str, Any]) -> TelegramUpdateCommand | None:
    """Extract /command + args from a Telegram update message."""

    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    chat = message.get("chat")
    from_user = message.get("from")
    if not isinstance(chat, dict) or not isinstance(from_user, dict):
        return None
    chat_id = chat.get("id")
    user_id = from_user.get("id")
    if not isinstance(chat_id, int) or not isinstance(user_id, int):
        return None

    stripped = text.strip()
    if not stripped.startswith("/"):
        return TelegramUpdateCommand(
            chat_id=chat_id,
            telegram_user_id=user_id,
            text=stripped,
            command=None,
            args=None,
        )

    first, _, rest = stripped.partition(" ")
    # Telegram may send /start@BotName
    command = first[1:].split("@", 1)[0].lower()
    args = rest.strip() or None
    return TelegramUpdateCommand(
        chat_id=chat_id,
        telegram_user_id=user_id,
        text=stripped,
        command=command,
        args=args,
    )
