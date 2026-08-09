"""Domain models and notification copy for the product Telegram bot."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class TelegramBotError(Exception):
    """Base domain error for the Telegram bot."""


class TelegramBotValidationError(TelegramBotError):
    """Invalid update payload or deep-link token."""


class TelegramBotNotFoundError(TelegramBotError):
    """Referenced user was not found."""


class TelegramNotifyKind(StrEnum):
    PUBLISH_SUCCESS = "publish_success"
    PUBLISH_ERROR = "publish_error"
    PACK_GENERATED = "pack_generated"


@dataclass(frozen=True, slots=True)
class TelegramUserStatus:
    user_id: UUID
    telegram_id: int | None
    subscription_status: str
    subscription_ends_at: str | None
    ai_coins: int


@dataclass(frozen=True, slots=True)
class TelegramUpdateCommand:
    chat_id: int
    telegram_user_id: int
    text: str
    command: str | None
    args: str | None


def build_deep_link_payload(
    user_id: UUID,
    *,
    secret: str,
    ttl_seconds: int = 3_600,
    now: int | None = None,
) -> str:
    """Build a signed /start payload: link_<uid>_<ts>_<sig16>."""

    if not secret.strip():
        raise TelegramBotValidationError("Deep-link signing secret is not configured.")
    ts = int(now if now is not None else time.time())
    uid = user_id.hex
    msg = f"{uid}.{ts}.{ttl_seconds}"
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[
        :16
    ]
    return f"link_{uid}_{ts}_{ttl_seconds}_{sig}"


def parse_deep_link_payload(
    payload: str,
    *,
    secret: str,
    now: int | None = None,
) -> UUID:
    """Validate and extract user id from a signed deep-link payload."""

    cleaned = payload.strip()
    if cleaned.startswith("/start"):
        cleaned = cleaned[6:].strip()
    if cleaned.startswith("link_"):
        cleaned = cleaned[5:]
    parts = cleaned.split("_")
    if len(parts) != 4:
        raise TelegramBotValidationError("Некорректная ссылка привязки аккаунта.")
    uid_hex, ts_raw, ttl_raw, sig = parts
    try:
        user_id = UUID(hex=uid_hex)
        ts = int(ts_raw)
        ttl = int(ttl_raw)
    except (ValueError, TypeError) as exc:
        raise TelegramBotValidationError("Некорректная ссылка привязки аккаунта.") from exc

    msg = f"{uid_hex}.{ts}.{ttl}"
    expected = hmac.new(
        secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(expected, sig):
        raise TelegramBotValidationError("Ссылка привязки повреждена или подделана.")

    current = int(now if now is not None else time.time())
    if current - ts > ttl or ts - current > 60:
        raise TelegramBotValidationError("Ссылка привязки истекла. Создайте новую в веб-кабинете.")

    return user_id


def message_publish_success(*, platform: str, product_id: str) -> str:
    label = "WB" if platform.lower() in {"wb", "wildberries"} else "Ozon"
    return (
        f"Ваша карточка успешно опубликована на {label}.\n"
        f"Артикул / ID: {product_id}"
    )


def message_publish_error(*, platform: str, product_id: str, detail: str | None = None) -> str:
    label = "WB" if platform.lower() in {"wb", "wildberries"} else "Ozon"
    base = f"Ошибка публикации на {label} (ID: {product_id})."
    if detail:
        return f"{base}\n{detail[:500]}"
    return base


def message_pack_generated(*, title: str | None = None) -> str:
    if title:
        return f"Сгенерирован новый сет: {title[:120]}"
    return "Сгенерирован новый сет."


def message_start_linked() -> str:
    return (
        "Аккаунт AI Card Master привязан.\n"
        "Вы будете получать уведомления о публикации и генерации сетов.\n\n"
        "Команды:\n"
        "/status — подписка и баланс генераций\n"
        "/start — повторная привязка по deep link"
    )


def message_start_need_link(*, bot_username: str) -> str:
    username = bot_username.lstrip("@") or "боте"
    return (
        "Чтобы привязать аккаунт, откройте deep link из веб-кабинета "
        f"(Профиль → Интеграции) или перейдите по ссылке вида:\n"
        f"https://t.me/{username}?start=link_…"
    )


def message_status(view: TelegramUserStatus) -> str:
    ends = view.subscription_ends_at or "—"
    return (
        "Статус аккаунта AI Card Master\n"
        f"Подписка: {view.subscription_status}\n"
        f"Действует до: {ends}\n"
        f"Баланс генераций (AI-коины): {view.ai_coins}"
    )


def message_unlinked() -> str:
    return (
        "Telegram ещё не привязан к аккаунту.\n"
        "Откройте deep link из веб-кабинета или выполните /start со ссылкой привязки."
    )
