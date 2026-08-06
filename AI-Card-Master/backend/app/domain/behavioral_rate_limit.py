"""Behavioral rate limiting and CAPTCHA challenge domain types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaptchaProvider(StrEnum):
    """Supported CAPTCHA verification backends."""

    TURNSTILE = "turnstile"
    RECAPTCHA = "recaptcha"


class CaptchaChallengeCode(StrEnum):
    """Machine-readable API codes for CAPTCHA flow."""

    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"


@dataclass(frozen=True, slots=True)
class BehavioralRateDecision:
    """Outcome of a generation-frequency check for one visitor."""

    allowed: bool
    request_count: int
    limit: int
    retry_after_seconds: int = 0
    captcha_required: bool = False
    subject_key: str = ""


@dataclass(frozen=True, slots=True)
class CaptchaVerificationResult:
    """Provider siteverify outcome."""

    success: bool
    provider: CaptchaProvider
    hostname: str | None = None
    error_codes: tuple[str, ...] = ()


class CaptchaRequiredError(Exception):
    """Raised when generation must pause until CAPTCHA is solved."""

    def __init__(
        self,
        *,
        retry_after_seconds: int,
        subject_key: str,
        message: str | None = None,
    ) -> None:
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        self.subject_key = subject_key
        self.message = message or (
            "Abnormal generation frequency detected. Complete CAPTCHA to continue."
        )
        self.code = CaptchaChallengeCode.CAPTCHA_REQUIRED
        super().__init__(self.message)


class CaptchaVerificationError(Exception):
    """Raised when the submitted CAPTCHA token is missing or invalid."""

    def __init__(self, message: str, *, error_codes: tuple[str, ...] = ()) -> None:
        self.message = message
        self.error_codes = error_codes
        super().__init__(message)
