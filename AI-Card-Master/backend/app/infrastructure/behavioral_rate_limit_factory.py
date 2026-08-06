"""Factory wiring for behavioral rate limiting / CAPTCHA use case."""

from __future__ import annotations

from app.application.behavioral_rate_limit_service import BehavioralRateLimitService
from app.core.config import Settings, get_settings
from app.infrastructure.security.captcha_verifier import CaptchaVerifierClient
from app.infrastructure.security.visitor_behavioral_store import (
    RedisVisitorBehavioralStore,
)


def build_behavioral_rate_limit_service(
    settings: Settings | None = None,
) -> BehavioralRateLimitService:
    """Compose Redis store + CAPTCHA verifier into the application service."""

    cfg = settings or get_settings()
    return BehavioralRateLimitService(
        RedisVisitorBehavioralStore(),
        CaptchaVerifierClient(cfg),
        enabled=cfg.security_behavioral_rate_enabled,
        limit_per_window=cfg.security_generation_requests_per_minute,
        window_seconds=cfg.security_generation_rate_window_seconds,
        captcha_block_ttl_seconds=cfg.security_captcha_block_ttl_seconds,
    )
