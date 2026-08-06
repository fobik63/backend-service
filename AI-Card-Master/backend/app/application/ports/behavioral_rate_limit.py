"""Ports for visitor behavioral rate limiting and CAPTCHA verification."""

from __future__ import annotations

from typing import Protocol

from app.domain.behavioral_rate_limit import (
    CaptchaProvider,
    CaptchaVerificationResult,
)


class VisitorBehavioralStorePort(Protocol):
    """Redis-backed counters and temporary CAPTCHA blocks per visitor."""

    async def is_captcha_blocked(self, *, subject_key: str) -> bool:
        """Return True when the subject must solve CAPTCHA before generating."""

        ...

    async def get_captcha_block_ttl(self, *, subject_key: str) -> int:
        """Seconds remaining on the CAPTCHA block (0 if not blocked)."""

        ...

    async def increment_generation_counter(
        self,
        *,
        subject_key: str,
        window_seconds: int,
    ) -> int:
        """Increment generation attempts in the sliding window; return new count."""

        ...

    async def set_captcha_block(self, *, subject_key: str, ttl_seconds: int) -> None:
        """Mark subject as CAPTCHA-blocked for ``ttl_seconds``."""

        ...

    async def clear_captcha_block(
        self,
        *,
        subject_key: str,
        window_seconds: int,
    ) -> None:
        """Remove CAPTCHA block and reset the generation counter window."""

        ...


class CaptchaVerifierPort(Protocol):
    """Validate a frontend CAPTCHA token with the configured provider API."""

    async def verify(
        self,
        *,
        token: str,
        remote_ip: str | None = None,
        provider: CaptchaProvider | None = None,
    ) -> CaptchaVerificationResult:
        """Call Turnstile / reCAPTCHA siteverify and return a typed result."""

        ...
