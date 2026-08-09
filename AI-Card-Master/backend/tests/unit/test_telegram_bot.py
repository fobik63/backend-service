"""Unit tests for Telegram bot deep-link signing and command parsing."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.telegram_bot import (
    TelegramBotValidationError,
    build_deep_link_payload,
    message_pack_generated,
    message_publish_error,
    message_publish_success,
    parse_deep_link_payload,
)
from app.infrastructure.telegram.update_parser import extract_bot_command


def test_deep_link_roundtrip() -> None:
    user_id = uuid4()
    secret = "unit-test-telegram-secret"
    payload = build_deep_link_payload(user_id, secret=secret, ttl_seconds=600, now=1_700_000_000)
    parsed = parse_deep_link_payload(payload, secret=secret, now=1_700_000_100)
    assert parsed == user_id


def test_deep_link_rejects_tampering() -> None:
    user_id = uuid4()
    secret = "unit-test-telegram-secret"
    payload = build_deep_link_payload(user_id, secret=secret, now=1_700_000_000)
    tampered = payload[:-2] + ("ab" if not payload.endswith("ab") else "cd")
    with pytest.raises(TelegramBotValidationError):
        parse_deep_link_payload(tampered, secret=secret, now=1_700_000_100)


def test_deep_link_expires() -> None:
    user_id = uuid4()
    secret = "unit-test-telegram-secret"
    payload = build_deep_link_payload(
        user_id, secret=secret, ttl_seconds=60, now=1_700_000_000
    )
    with pytest.raises(TelegramBotValidationError):
        parse_deep_link_payload(payload, secret=secret, now=1_700_000_200)


def test_extract_start_command_with_payload() -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "text": "/start@MyBot link_abc",
            "chat": {"id": 42},
            "from": {"id": 42},
        },
    }
    command = extract_bot_command(update)
    assert command is not None
    assert command.command == "start"
    assert command.args == "link_abc"
    assert command.chat_id == 42


def test_notify_copy() -> None:
    assert "WB" in message_publish_success(platform="wb", product_id="123")
    assert "Ошибка публикации" in message_publish_error(platform="ozon", product_id="9")
    assert "Сгенерирован новый сет" in message_pack_generated(title="Кроссовки")
