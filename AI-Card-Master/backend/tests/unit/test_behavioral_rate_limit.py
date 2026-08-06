"""Unit tests for plan §35 behavioral rate limiting + CAPTCHA_REQUIRED."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.application.behavioral_rate_limit_service import (
    BehavioralRateLimitService,
    normalize_visitor_id,
    resolve_subject_key,
)
from app.core.http_errors import shape_http_exception_body
from app.domain.behavioral_rate_limit import (
    CaptchaChallengeCode,
    CaptchaProvider,
    CaptchaRequiredError,
    CaptchaVerificationError,
    CaptchaVerificationResult,
)


class FakeStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.blocks: dict[str, int] = {}
        self.cleared: list[tuple[str, int]] = []

    async def is_captcha_blocked(self, *, subject_key: str) -> bool:
        return subject_key in self.blocks

    async def get_captcha_block_ttl(self, *, subject_key: str) -> int:
        return self.blocks.get(subject_key, 0)

    async def increment_generation_counter(
        self,
        *,
        subject_key: str,
        window_seconds: int,
    ) -> int:
        self.counts[subject_key] = self.counts.get(subject_key, 0) + 1
        return self.counts[subject_key]

    async def set_captcha_block(self, *, subject_key: str, ttl_seconds: int) -> None:
        self.blocks[subject_key] = ttl_seconds

    async def clear_captcha_block(self, *, subject_key: str, window_seconds: int) -> None:
        self.blocks.pop(subject_key, None)
        self.counts.pop(subject_key, None)
        self.cleared.append((subject_key, window_seconds))


class FakeVerifier:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls: list[dict[str, object]] = []

    async def verify(
        self,
        *,
        token: str,
        remote_ip: str | None = None,
        provider: CaptchaProvider | None = None,
    ) -> CaptchaVerificationResult:
        self.calls.append(
            {"token": token, "remote_ip": remote_ip, "provider": provider}
        )
        return CaptchaVerificationResult(
            success=self.success,
            provider=provider or CaptchaProvider.TURNSTILE,
            error_codes=() if self.success else ("invalid-input-response",),
        )


def test_normalize_visitor_id() -> None:
    assert normalize_visitor_id("  abcdefghij  ") == "abcdefghij"
    assert normalize_visitor_id("bad id!") is None
    assert normalize_visitor_id(None) is None


def test_resolve_subject_key_prefers_visitor() -> None:
    user_id = uuid4()
    assert resolve_subject_key(visitor_id="visitorFingerprint1", user_id=user_id) == (
        "visitor:visitorFingerprint1"
    )
    assert resolve_subject_key(visitor_id=None, user_id=user_id) == f"user:{user_id}"


@pytest.mark.asyncio
async def test_assert_generation_allows_within_limit() -> None:
    store = FakeStore()
    service = BehavioralRateLimitService(
        store,
        FakeVerifier(),
        limit_per_window=3,
        window_seconds=60,
        captcha_block_ttl_seconds=300,
    )
    decision = await service.assert_generation_allowed(
        visitor_id="visitorFingerprint1",
        user_id=uuid4(),
    )
    assert decision.allowed is True
    assert decision.request_count == 1


@pytest.mark.asyncio
async def test_assert_generation_raises_captcha_required_on_burst() -> None:
    store = FakeStore()
    service = BehavioralRateLimitService(
        store,
        FakeVerifier(),
        limit_per_window=2,
        window_seconds=60,
        captcha_block_ttl_seconds=600,
    )
    visitor = "visitorFingerprint99"
    await service.assert_generation_allowed(visitor_id=visitor, user_id=None)
    await service.assert_generation_allowed(visitor_id=visitor, user_id=None)
    with pytest.raises(CaptchaRequiredError) as exc:
        await service.assert_generation_allowed(visitor_id=visitor, user_id=None)
    assert exc.value.code == CaptchaChallengeCode.CAPTCHA_REQUIRED
    assert store.blocks[f"visitor:{visitor}"] == 600

    with pytest.raises(CaptchaRequiredError):
        await service.assert_generation_allowed(visitor_id=visitor, user_id=None)


@pytest.mark.asyncio
async def test_credits_do_not_bypass_behavioral_limit() -> None:
    """Burst detection is independent of coin balance (checked only at API layer)."""

    store = FakeStore()
    service = BehavioralRateLimitService(
        store,
        FakeVerifier(),
        limit_per_window=1,
        window_seconds=60,
        captcha_block_ttl_seconds=900,
    )
    await service.assert_generation_allowed(
        visitor_id="richVisitorId01",
        user_id=uuid4(),
    )
    with pytest.raises(CaptchaRequiredError) as exc:
        await service.assert_generation_allowed(
            visitor_id="richVisitorId01",
            user_id=uuid4(),
        )
    assert exc.value.code.value == "CAPTCHA_REQUIRED"


@pytest.mark.asyncio
async def test_verify_and_clear_block() -> None:
    store = FakeStore()
    store.blocks["visitor:visitorFingerprint1"] = 900
    store.counts["visitor:visitorFingerprint1"] = 20
    verifier = FakeVerifier(success=True)
    service = BehavioralRateLimitService(
        store,
        verifier,
        limit_per_window=5,
        window_seconds=60,
        captcha_block_ttl_seconds=900,
    )
    result = await service.verify_and_clear_block(
        token="turnstile-token-value",
        visitor_id="visitorFingerprint1",
        user_id=None,
        remote_ip="203.0.113.10",
    )
    assert result.success is True
    assert "visitor:visitorFingerprint1" not in store.blocks
    assert store.cleared == [("visitor:visitorFingerprint1", 60)]


@pytest.mark.asyncio
async def test_verify_rejects_invalid_token() -> None:
    service = BehavioralRateLimitService(
        FakeStore(),
        FakeVerifier(success=False),
        limit_per_window=5,
        window_seconds=60,
        captcha_block_ttl_seconds=900,
    )
    with pytest.raises(CaptchaVerificationError):
        await service.verify_and_clear_block(
            token="bad-token",
            visitor_id="visitorFingerprint1",
            user_id=None,
        )


def test_shape_http_exception_promotes_captcha_code() -> None:
    exc = HTTPException(
        status_code=429,
        detail={
            "code": CaptchaChallengeCode.CAPTCHA_REQUIRED.value,
            "message": "Solve CAPTCHA.",
        },
        headers={"Retry-After": "120"},
    )
    body = shape_http_exception_body(exc)
    assert body["success"] is False
    assert body["code"] == "CAPTCHA_REQUIRED"
    assert body["detail"] == "Solve CAPTCHA."


def test_captcha_required_json_via_test_client() -> None:
    probe = FastAPI()

    @probe.exception_handler(HTTPException)
    async def _handler(_: object, exc: HTTPException):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content=shape_http_exception_body(exc),
            headers=exc.headers,
        )

    @probe.get("/boom")
    async def boom() -> None:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CaptchaChallengeCode.CAPTCHA_REQUIRED.value,
                "message": "Solve CAPTCHA.",
            },
            headers={"Retry-After": "120"},
        )

    client = TestClient(probe)
    response = client.get("/boom")
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "CAPTCHA_REQUIRED"
    assert response.headers.get("retry-after") == "120"


def test_verify_captcha_route_path_constant() -> None:
    """Endpoint path from plan §35 (wired in app.api.captcha + main)."""

    from pathlib import Path

    source = Path("app/api/captcha.py").read_text(encoding="utf-8")
    assert '"/api/v1/verify-captcha"' in source
    assert "CAPTCHA_REQUIRED" in Path("app/domain/behavioral_rate_limit.py").read_text(
        encoding="utf-8"
    )