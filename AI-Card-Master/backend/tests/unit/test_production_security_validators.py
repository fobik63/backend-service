"""Production security invariant validators (S3, S4, S6)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _base(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "j" * 64,
        "APP_ENV": "development",
        # Do not inherit the test-suite's dev bypass when a case switches to
        # production: each assertion must reach the invariant it targets.
        "CAPTCHA_BYPASS_WHEN_UNCONFIGURED": False,
    }
    data.update(overrides)
    return data


def test_production_rejects_captcha_bypass() -> None:
    with pytest.raises(ValidationError, match="CAPTCHA_BYPASS_WHEN_UNCONFIGURED"):
        Settings(
            **_base(
                APP_ENV="production",
                CAPTCHA_BYPASS_WHEN_UNCONFIGURED=True,
                ADMIN_PANEL_TOKEN_SECRET="a" * 32,
                PASSWORD_PEPPER="p" * 32,
            )
        )


def test_production_requires_distinct_admin_panel_secret() -> None:
    jwt = "j" * 64
    with pytest.raises(ValidationError, match="ADMIN_PANEL_TOKEN_SECRET"):
        Settings(
            **_base(
                APP_ENV="production",
                JWT_SECRET_KEY=jwt,
                ADMIN_PANEL_TOKEN_SECRET="",
                PASSWORD_PEPPER="p" * 32,
            )
        )

    with pytest.raises(ValidationError, match="must not equal JWT_SECRET_KEY"):
        Settings(
            **_base(
                APP_ENV="production",
                JWT_SECRET_KEY=jwt,
                ADMIN_PANEL_TOKEN_SECRET=jwt,
                PASSWORD_PEPPER="p" * 32,
            )
        )


def test_production_requires_password_pepper_length() -> None:
    with pytest.raises(ValidationError, match="PASSWORD_PEPPER"):
        Settings(
            **_base(
                APP_ENV="production",
                ADMIN_PANEL_TOKEN_SECRET="a" * 32,
                PASSWORD_PEPPER="short",
            )
        )


def test_production_accepts_strong_security_secrets() -> None:
    settings = Settings(
        **_base(
            APP_ENV="production",
            ADMIN_PANEL_TOKEN_SECRET="a" * 32,
            PASSWORD_PEPPER="p" * 32,
            CAPTCHA_BYPASS_WHEN_UNCONFIGURED=False,
        )
    )
    assert settings.effective_admin_panel_token_secret == "a" * 32


def test_dev_allows_jwt_fallback_for_admin_secret() -> None:
    settings = Settings(**_base(ADMIN_PANEL_TOKEN_SECRET=""))
    assert settings.effective_admin_panel_token_secret == "j" * 64


def test_production_requires_yookassa_webhook_ip_enforcement() -> None:
    with pytest.raises(ValidationError, match="YOOKASSA_WEBHOOK_IP_ENFORCEMENT"):
        Settings(
            **_base(
                APP_ENV="production",
                ADMIN_PANEL_TOKEN_SECRET="a" * 32,
                PASSWORD_PEPPER="p" * 32,
                YOOKASSA_WEBHOOK_IP_ENFORCEMENT=False,
            )
        )


def test_production_requires_telegram_webhook_secret_when_url_set() -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_WEBHOOK_SECRET"):
        Settings(
            **_base(
                APP_ENV="production",
                ADMIN_PANEL_TOKEN_SECRET="a" * 32,
                PASSWORD_PEPPER="p" * 32,
                TELEGRAM_BOT_WEBHOOK_URL="https://api.example.com/api/v1/telegram/webhook",
                TELEGRAM_BOT_WEBHOOK_SECRET="",
            )
        )
