"""Telegram Login Widget payload verification (Bot API)."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Mapping

from app.core.config import get_settings


class TelegramAuthError(ValueError):
    """Telegram Login Widget payload failed verification."""


def _bot_token() -> str:
    settings = get_settings()
    # Prefer dedicated login bot; fall back to user-facing / error bots.
    for candidate in (
        settings.telegram_login_bot_token,
        settings.telegram_user_bot_token,
        settings.telegram_error_bot_token,
    ):
        if candidate is None:
            continue
        value = candidate.get_secret_value().strip()
        if value:
            return value
    raise TelegramAuthError("Telegram bot token is not configured.")


def verify_telegram_login(
    payload: Mapping[str, object],
    *,
    max_age_seconds: int = 86400,
) -> dict[str, object]:
    """Validate ``hash`` per https://core.telegram.org/widgets/login.

    Returns a cleaned dict with required ``id`` (int) and optional profile fields.
    """

    raw_hash = str(payload.get("hash") or "").strip()
    if not raw_hash:
        raise TelegramAuthError("Missing Telegram hash.")

    check_pairs: list[str] = []
    for key in sorted(payload.keys()):
        if key == "hash":
            continue
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        check_pairs.append(f"{key}={text}")
    data_check_string = "\n".join(check_pairs)

    secret_key = hashlib.sha256(_bot_token().encode("utf-8")).digest()
    computed = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(computed, raw_hash):
        raise TelegramAuthError("Invalid Telegram login signature.")

    try:
        auth_date = int(payload.get("auth_date") or 0)
    except (TypeError, ValueError) as exc:
        raise TelegramAuthError("Invalid auth_date.") from exc
    if auth_date <= 0:
        raise TelegramAuthError("Invalid auth_date.")
    if int(time.time()) - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram login payload expired.")

    try:
        telegram_id = int(payload.get("id") or 0)
    except (TypeError, ValueError) as exc:
        raise TelegramAuthError("Invalid Telegram user id.") from exc
    if telegram_id <= 0:
        raise TelegramAuthError("Invalid Telegram user id.")

    cleaned: dict[str, object] = {
        "id": telegram_id,
        "auth_date": auth_date,
        "hash": raw_hash,
    }
    for optional in ("first_name", "last_name", "username", "photo_url"):
        raw = payload.get(optional)
        if isinstance(raw, str) and raw.strip():
            cleaned[optional] = raw.strip()[:256]
    return cleaned
