"""Unit tests for Telegram Login Widget hash verification."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from app.infrastructure.security.telegram_login import (
    TelegramAuthError,
    verify_telegram_login,
)


def _sign(payload: dict[str, object], bot_token: str) -> str:
    pairs = [f"{k}={payload[k]}" for k in sorted(payload) if k != "hash"]
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    return hmac.new(secret, "\n".join(pairs).encode("utf-8"), hashlib.sha256).hexdigest()


def test_verify_telegram_login_accepts_valid_payload() -> None:
    token = "123456:ABC-DEF"
    payload: dict[str, object] = {
        "id": 42,
        "first_name": "Ada",
        "username": "ada",
        "auth_date": int(time.time()),
    }
    payload["hash"] = _sign(payload, token)

    with patch(
        "app.infrastructure.security.telegram_login._bot_token",
        return_value=token,
    ):
        verified = verify_telegram_login(payload)

    assert verified["id"] == 42
    assert verified["username"] == "ada"


def test_verify_telegram_login_rejects_bad_hash() -> None:
    token = "123456:ABC-DEF"
    payload: dict[str, object] = {
        "id": 42,
        "first_name": "Ada",
        "auth_date": int(time.time()),
        "hash": "0" * 64,
    }
    with patch(
        "app.infrastructure.security.telegram_login._bot_token",
        return_value=token,
    ):
        with pytest.raises(TelegramAuthError, match="signature"):
            verify_telegram_login(payload)


def test_verify_telegram_login_skips_empty_optional_fields() -> None:
    token = "123456:ABC-DEF"
    base: dict[str, object] = {
        "id": 7,
        "first_name": "Lin",
        "auth_date": int(time.time()),
    }
    signed = dict(base)
    signed["hash"] = _sign(signed, token)
    # Empty optionals must not break the signature check.
    signed["last_name"] = ""
    signed["username"] = ""
    signed["photo_url"] = ""

    with patch(
        "app.infrastructure.security.telegram_login._bot_token",
        return_value=token,
    ):
        verified = verify_telegram_login(signed)
    assert verified["id"] == 7
