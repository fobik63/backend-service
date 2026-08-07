"""Cascading HTTP rate limiting via slowapi + Redis (security store).

Tiers (all windows are per-minute rolling buckets):
1. Global: ``SLOWAPI_GLOBAL_PER_MINUTE`` requests per client IP (default limits).
2. Auth brute-force: shared ``SLOWAPI_AUTH_PER_MINUTE`` per IP on login/register.
3. Generations: shared ``SLOWAPI_GENERATIONS_PER_MINUTE`` per authenticated user_id.

Exceeded limits return HTTP 429 with a stable JSON body and ``Retry-After``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.wrappers import Limit

from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_and_validate_token

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_AFTER_SECONDS = 60


def get_client_ip_key(request: Request) -> str:
    """Rate-limit key: real client IP (CF / trusted proxy aware)."""

    cached = getattr(request.state, "client_ip", None)
    if isinstance(cached, str) and cached.strip():
        return cached.strip()

    settings = get_settings()
    return resolve_client_ip(
        request,
        trust_cloudflare=settings.cloudflare_trust_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )


def get_user_id_key(request: Request) -> str:
    """Rate-limit key: JWT ``sub`` (user_id); falls back to IP when unauthenticated."""

    authorization = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    ) or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            payload = decode_and_validate_token(
                token.strip(),
                expected_type="access",
            )
            subject = str(payload.get("sub") or "").strip()
            if subject:
                return f"user:{subject}"
        except InvalidTokenError:
            pass

    return f"ip:{get_client_ip_key(request)}"


def _build_storage_uri() -> str:
    """Use the security Redis (noeviction) for durable rate-limit counters."""

    settings = get_settings()
    if not settings.slowapi_enabled:
        return "memory://"
    return settings.effective_redis_security_url


def build_limiter() -> Limiter:
    """Construct the process-wide Limiter (Redis-backed when enabled)."""

    settings = get_settings()
    return Limiter(
        key_func=get_client_ip_key,
        default_limits=[f"{settings.slowapi_global_per_minute}/minute"],
        storage_uri=_build_storage_uri(),
        key_prefix="slowapi",
        # Keep False: FastAPI endpoints return Pydantic models / dicts, and
        # slowapi can only mutate headers on an explicit Response instance.
        # Retry-After is still set by ``rate_limit_exceeded_handler``.
        headers_enabled=False,
        retry_after="delta-seconds",
        in_memory_fallback_enabled=True,
        enabled=settings.slowapi_enabled,
    )


limiter = build_limiter()

# Shared cascades: one budget for login+register; one for all /generations/*.
auth_bruteforce_limit = limiter.shared_limit(
    lambda: f"{get_settings().slowapi_auth_per_minute}/minute",
    scope="auth_bruteforce",
    key_func=get_client_ip_key,
    override_defaults=False,
    error_message="Rate limit exceeded",
)

generations_user_limit = limiter.shared_limit(
    lambda: f"{get_settings().slowapi_generations_per_minute}/minute",
    scope="generations_user",
    key_func=get_user_id_key,
    override_defaults=False,
    error_message="Rate limit exceeded",
)


def _retry_after_seconds(request: Request, exc: RateLimitExceeded) -> int:
    """Best-effort seconds until the limiting window resets."""

    current_limit: Any = getattr(request.state, "view_rate_limit", None)
    app_limiter = getattr(request.app.state, "limiter", None)
    if current_limit is not None and app_limiter is not None:
        try:
            window_stats = app_limiter.limiter.get_window_stats(
                current_limit[0],
                *current_limit[1],
            )
            reset_at = 1 + int(window_stats[0])
            return max(int(reset_at - time.time()), 1)
        except Exception:
            logger.debug("Could not derive Retry-After from window stats", exc_info=True)

    limit_obj: Limit | None = getattr(exc, "limit", None)
    if limit_obj is not None and getattr(limit_obj, "limit", None) is not None:
        try:
            # Fall back to the configured window length (e.g. 60 for */minute).
            granularity = getattr(limit_obj.limit, "GRANULARITY", None)
            if granularity is not None and getattr(granularity, "seconds", 0):
                return max(int(granularity.seconds), 1)
        except Exception:
            logger.debug("Could not derive Retry-After from limit item", exc_info=True)

    return _DEFAULT_RETRY_AFTER_SECONDS


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    """Return the project-standard 429 JSON body + Retry-After header."""

    retry_after = _retry_after_seconds(request, exc)
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
