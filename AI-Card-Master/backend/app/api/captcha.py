"""CAPTCHA challenge API: verify frontend tokens and clear behavioral blocks."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import get_current_user
from app.application.behavioral_rate_limit_service import BehavioralRateLimitService
from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings
from app.domain.behavioral_rate_limit import (
    CaptchaChallengeCode,
    CaptchaProvider,
    CaptchaRequiredError,
    CaptchaVerificationError,
)
from app.infrastructure.behavioral_rate_limit_factory import (
    build_behavioral_rate_limit_service,
)
from app.infrastructure.redis import RedisUnavailableError
from app.models.user import User

router = APIRouter(tags=["security"])

_SECURITY_REDIS_RETRY_AFTER = "5"


class StrictAPIModel(BaseModel):
    """Strict Pydantic v2 base for security payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class VerifyCaptchaRequest(StrictAPIModel):
    """Token returned by Turnstile / reCAPTCHA widget on the frontend."""

    token: str = Field(..., min_length=10, max_length=4096)
    provider: Literal["turnstile", "recaptcha"] | None = Field(
        default=None,
        description="Optional override; defaults to CAPTCHA_PROVIDER / auto.",
    )
    visitor_id: str | None = Field(
        default=None,
        alias="visitorId",
        min_length=8,
        max_length=128,
        description="FingerprintJS visitorId (also accepted via X-Visitor-Id).",
    )


class VerifyCaptchaResponse(StrictAPIModel):
    """Confirmation that the temporary CAPTCHA block was lifted."""

    success: bool = True
    cleared: bool = True
    provider: str


def get_behavioral_rate_limit_service() -> BehavioralRateLimitService:
    """Request-scoped behavioral rate / CAPTCHA use case."""

    return build_behavioral_rate_limit_service()


def captcha_required_http_exception(exc: CaptchaRequiredError) -> HTTPException:
    """Map domain CAPTCHA gate to FastAPI HTTPException with structured detail."""

    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": CaptchaChallengeCode.CAPTCHA_REQUIRED.value,
            "message": exc.message,
        },
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def security_store_unavailable_http_exception(
    exc: RedisUnavailableError,
) -> HTTPException:
    """Fail-closed when behavioral Redis is down during generation enqueue."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "SECURITY_CONTROLS_UNAVAILABLE",
            "message": "Security controls temporarily unavailable. Retry shortly.",
        },
        headers={"Retry-After": _SECURITY_REDIS_RETRY_AFTER},
    )


async def enforce_generation_behavioral_limit(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        BehavioralRateLimitService,
        Depends(get_behavioral_rate_limit_service),
    ],
    visitor_id: Annotated[
        str | None,
        Header(
            alias="X-Visitor-Id",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None,
) -> None:
    """Block anomalous generation starts even when the user still has credits."""

    try:
        await service.assert_generation_allowed(
            visitor_id=visitor_id,
            user_id=current_user.id,
        )
    except CaptchaRequiredError as exc:
        raise captcha_required_http_exception(exc) from exc
    except RedisUnavailableError as exc:
        raise security_store_unavailable_http_exception(exc) from exc


@router.post(
    "/api/v1/verify-captcha",
    response_model=VerifyCaptchaResponse,
    summary="Verify CAPTCHA and clear temporary generation block",
    description=(
        "Accepts a Turnstile or reCAPTCHA token from the frontend, validates it "
        "via the provider siteverify API, and removes the temporary CAPTCHA block "
        "for the visitorId / account."
    ),
)
async def verify_captcha(
    payload: VerifyCaptchaRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        BehavioralRateLimitService,
        Depends(get_behavioral_rate_limit_service),
    ],
    visitor_header: Annotated[
        str | None,
        Header(
            alias="X-Visitor-Id",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None,
) -> VerifyCaptchaResponse:
    """Validate CAPTCHA token and lift the behavioral generation block."""

    settings = get_settings()
    remote_ip = resolve_client_ip(
        request,
        trust_cloudflare=settings.cloudflare_trust_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )
    provider = CaptchaProvider(payload.provider) if payload.provider else None
    visitor_id = payload.visitor_id or visitor_header

    try:
        result = await service.verify_and_clear_block(
            token=payload.token,
            visitor_id=visitor_id,
            user_id=current_user.id,
            remote_ip=remote_ip,
            provider=provider,
        )
    except CaptchaVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CAPTCHA_INVALID",
                "message": exc.message,
                "error_codes": list(exc.error_codes),
            },
        ) from exc
    except RedisUnavailableError as exc:
        raise security_store_unavailable_http_exception(exc) from exc

    return VerifyCaptchaResponse(
        success=True,
        cleared=True,
        provider=result.provider.value,
    )


# Re-export for type checkers / tests
__all__ = [
    "router",
    "enforce_generation_behavioral_limit",
    "captcha_required_http_exception",
    "security_store_unavailable_http_exception",
    "VerifyCaptchaRequest",
    "VerifyCaptchaResponse",
]
