"""Safe test environment defaults; no real external service is contacted."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_card_master_test",
)
os.environ.setdefault("JWT_SECRET_KEY", "x" * 64)
os.environ.setdefault("STABLE_DIFFUSION_API_KEY", "test-stability-key")
os.environ.setdefault("MIDJOURNEY_PROVIDERS", "[]")
os.environ.setdefault("MIDJOURNEY_CALLBACK_BASE_URL", "https://api.test.example")
os.environ.setdefault(
    "MIDJOURNEY_WEBHOOK_TOKEN", "test-webhook-token-with-enough-entropy"
)
os.environ.setdefault(
    "MIDJOURNEY_REPLY_REF_SECRET", "test-reply-ref-secret-" + ("y" * 48)
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GENERATION_CHARGE_COINS", "false")
os.environ.setdefault("TELEGRAM_ERROR_LOGGING_ENABLED", "false")
os.environ.setdefault("ENABLE_THREE_D", "true")
# Prevent shared auth rate-limit counters from flaking TestClient suites.
os.environ.setdefault("SLOWAPI_ENABLED", "false")


@pytest.fixture(autouse=True)
def _disable_slowapi_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure process-wide Limiter stays off even if it was built enabled."""

    try:
        from app.core.rate_limit import limiter
    except Exception:
        return
    monkeypatch.setattr(limiter, "enabled", False)
