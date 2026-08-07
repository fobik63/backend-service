"""Use case: behavioral generation rate limits and CAPTCHA unblock."""

from __future__ import annotations

import logging
import re
from uuid import UUID

from app.application.ports.behavioral_rate_limit import (
    CaptchaVerifierPort,
    VisitorBehavioralStorePort,
)
from app.domain.behavioral_rate_limit import (
    BehavioralRateDecision,
    CaptchaProvider,
    CaptchaRequiredError,
    CaptchaVerificationError,
    CaptchaVerificationResult,
)

logger = logging.getLogger(__name__)

# FingerprintJS visitorId is typically a 20–32 char alphanumeric hash.
_VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def normalize_visitor_id(raw: str | None) -> str | None:
    """Validate and normalize a browser visitor fingerprint, or return None."""

    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if not _VISITOR_ID_RE.fullmatch(cleaned):
        return None
    return cleaned


def resolve_subject_key(*, visitor_id: str | None, user_id: UUID | None) -> str | None:
    """Prefer visitorId; fall back to authenticated user for credit-holding abusers."""

    normalized = normalize_visitor_id(visitor_id)
    if normalized is not None:
        return f"visitor:{normalized}"
    if user_id is not None:
        return f"user:{user_id}"
    return None


class BehavioralRateLimitService:
    """Detect anomalous generation frequency and gate on CAPTCHA verification."""

    def __init__(
        self,
        store: VisitorBehavioralStorePort,
        verifier: CaptchaVerifierPort,
        *,
        enabled: bool = True,
        limit_per_window: int = 8,
        window_seconds: int = 60,
        captcha_block_ttl_seconds: int = 900,
    ) -> None:
        if limit_per_window <= 0:
            raise ValueError("limit_per_window must be positive.")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")
        if captcha_block_ttl_seconds <= 0:
            raise ValueError("captcha_block_ttl_seconds must be positive.")
        self._store = store
        self._verifier = verifier
        self._enabled = enabled
        self._limit = limit_per_window
        self._window_seconds = window_seconds
        self._block_ttl = captcha_block_ttl_seconds

    async def assert_generation_allowed(
        self,
        *,
        visitor_id: str | None,
        user_id: UUID | None,
    ) -> BehavioralRateDecision:
        """Record a generation attempt; raise ``CaptchaRequiredError`` on anomaly.

        Runs even when the user still has AI coins — credits do not bypass abuse
        controls. When the feature is disabled or no subject can be resolved the
        check is skipped. Redis failures from the store propagate as
        ``RedisUnavailableError`` (fail-closed → HTTP 503 upstream).
        """

        if not self._enabled:
            return BehavioralRateDecision(
                allowed=True,
                request_count=0,
                limit=self._limit,
            )

        subject_key = resolve_subject_key(visitor_id=visitor_id, user_id=user_id)
        if subject_key is None:
            logger.debug("Behavioral rate limit skipped: no visitorId or user_id")
            return BehavioralRateDecision(
                allowed=True,
                request_count=0,
                limit=self._limit,
            )

        if await self._store.is_captcha_blocked(subject_key=subject_key):
            ttl = await self._store.get_captcha_block_ttl(subject_key=subject_key)
            raise CaptchaRequiredError(
                retry_after_seconds=ttl or self._block_ttl,
                subject_key=subject_key,
            )

        count = await self._store.increment_generation_counter(
            subject_key=subject_key,
            window_seconds=self._window_seconds,
        )
        if count > self._limit:
            await self._store.set_captcha_block(
                subject_key=subject_key,
                ttl_seconds=self._block_ttl,
            )
            logger.warning(
                "CAPTCHA block armed subject=%s count=%s limit=%s",
                subject_key,
                count,
                self._limit,
            )
            raise CaptchaRequiredError(
                retry_after_seconds=self._block_ttl,
                subject_key=subject_key,
            )

        return BehavioralRateDecision(
            allowed=True,
            request_count=count,
            limit=self._limit,
            subject_key=subject_key,
        )

    async def verify_and_clear_block(
        self,
        *,
        token: str,
        visitor_id: str | None,
        user_id: UUID | None,
        remote_ip: str | None = None,
        provider: CaptchaProvider | None = None,
    ) -> CaptchaVerificationResult:
        """Validate CAPTCHA token with the provider and lift the temporary block."""

        cleaned_token = (token or "").strip()
        if not cleaned_token:
            raise CaptchaVerificationError("CAPTCHA token is required.")

        subject_key = resolve_subject_key(visitor_id=visitor_id, user_id=user_id)
        if subject_key is None:
            raise CaptchaVerificationError(
                "visitorId (X-Visitor-Id) or authenticated user is required."
            )

        result = await self._verifier.verify(
            token=cleaned_token,
            remote_ip=remote_ip,
            provider=provider,
        )
        if not result.success:
            raise CaptchaVerificationError(
                "CAPTCHA verification failed.",
                error_codes=result.error_codes,
            )

        await self._store.clear_captcha_block(
            subject_key=subject_key,
            window_seconds=self._window_seconds,
        )
        logger.info(
            "CAPTCHA cleared subject=%s provider=%s",
            subject_key,
            result.provider.value,
        )
        return result
