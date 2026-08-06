"""Turnstile / reCAPTCHA siteverify HTTP clients."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.domain.behavioral_rate_limit import CaptchaProvider, CaptchaVerificationResult

logger = logging.getLogger(__name__)

_TURNSTILE_SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_RECAPTCHA_SITEVERIFY = "https://www.google.com/recaptcha/api/siteverify"


class CaptchaVerifierClient:
    """Validate CAPTCHA tokens against Cloudflare Turnstile or Google reCAPTCHA."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._timeout = httpx.Timeout(self._settings.captcha_verify_timeout_seconds)

    def _secret_for(self, provider: CaptchaProvider) -> str:
        if provider is CaptchaProvider.TURNSTILE:
            secret = self._settings.turnstile_secret_key
        else:
            secret = self._settings.recaptcha_secret_key
        if secret is None:
            return ""
        return secret.get_secret_value().strip()

    def resolve_provider(
        self,
        preferred: CaptchaProvider | None = None,
    ) -> CaptchaProvider:
        """Pick provider from explicit request, config default, or available secrets."""

        if preferred is not None:
            return preferred
        configured = (self._settings.captcha_provider or "auto").strip().lower()
        if configured == CaptchaProvider.TURNSTILE.value:
            return CaptchaProvider.TURNSTILE
        if configured == CaptchaProvider.RECAPTCHA.value:
            return CaptchaProvider.RECAPTCHA
        # auto: prefer Turnstile when both/neither are set (Cloudflare stack).
        if self._secret_for(CaptchaProvider.RECAPTCHA) and not self._secret_for(
            CaptchaProvider.TURNSTILE
        ):
            return CaptchaProvider.RECAPTCHA
        return CaptchaProvider.TURNSTILE

    async def verify(
        self,
        *,
        token: str,
        remote_ip: str | None = None,
        provider: CaptchaProvider | None = None,
    ) -> CaptchaVerificationResult:
        chosen = self.resolve_provider(provider)
        secret = self._secret_for(chosen)
        if not secret:
            if self._settings.captcha_bypass_when_unconfigured:
                logger.warning(
                    "CAPTCHA secret missing for %s; bypass enabled for non-prod",
                    chosen.value,
                )
                return CaptchaVerificationResult(success=True, provider=chosen)
            logger.error("CAPTCHA secret not configured for provider=%s", chosen.value)
            return CaptchaVerificationResult(
                success=False,
                provider=chosen,
                error_codes=("missing-input-secret",),
            )

        if chosen is CaptchaProvider.TURNSTILE:
            return await self._verify_turnstile(token=token, secret=secret, remote_ip=remote_ip)
        return await self._verify_recaptcha(token=token, secret=secret, remote_ip=remote_ip)

    async def _verify_turnstile(
        self,
        *,
        token: str,
        secret: str,
        remote_ip: str | None,
    ) -> CaptchaVerificationResult:
        payload: dict[str, Any] = {"secret": secret, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_TURNSTILE_SITEVERIFY, data=payload)
                body = response.json()
        except Exception:
            logger.warning("Turnstile siteverify request failed", exc_info=True)
            return CaptchaVerificationResult(
                success=False,
                provider=CaptchaProvider.TURNSTILE,
                error_codes=("network-error",),
            )
        return CaptchaVerificationResult(
            success=bool(body.get("success")),
            provider=CaptchaProvider.TURNSTILE,
            hostname=body.get("hostname"),
            error_codes=tuple(str(c) for c in (body.get("error-codes") or [])),
        )

    async def _verify_recaptcha(
        self,
        *,
        token: str,
        secret: str,
        remote_ip: str | None,
    ) -> CaptchaVerificationResult:
        payload: dict[str, Any] = {"secret": secret, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_RECAPTCHA_SITEVERIFY, data=payload)
                body = response.json()
        except Exception:
            logger.warning("reCAPTCHA siteverify request failed", exc_info=True)
            return CaptchaVerificationResult(
                success=False,
                provider=CaptchaProvider.RECAPTCHA,
                error_codes=("network-error",),
            )
        error_codes = body.get("error-codes") or body.get("error_codes") or []
        return CaptchaVerificationResult(
            success=bool(body.get("success")),
            provider=CaptchaProvider.RECAPTCHA,
            hostname=body.get("hostname"),
            error_codes=tuple(str(c) for c in error_codes),
        )
