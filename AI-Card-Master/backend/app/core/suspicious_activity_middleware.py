"""Middleware that scores each request for suspicious / abusive activity."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings
from app.core.input_sanitization import scan_text_for_threats
from app.infrastructure.cloudflare import get_cloudflare_client
from app.infrastructure.security.rate_limiter import (
    block_ip,
    check_rate_limit,
    is_ip_blocked,
    record_threat_event,
)

logger = logging.getLogger(__name__)


class SuspiciousActivityMiddleware(BaseHTTPMiddleware):
    """Rate-limit, score, and optionally auto-ban abusive clients."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.security_suspicious_middleware_enabled:
            return await call_next(request)

        path = request.url.path
        if path in {"/", "/health", "/health/live", "/health/ready"}:
            return await call_next(request)
        if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
            return await call_next(request)

        client_ip = resolve_client_ip(
            request,
            trust_cloudflare=settings.cloudflare_trust_headers,
            trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
        )
        request.state.client_ip = client_ip

        if await is_ip_blocked(client_ip):
            return _deny(
                status.HTTP_403_FORBIDDEN,
                "Access temporarily blocked due to suspicious activity.",
            )

        rate = await check_rate_limit(
            ip=client_ip,
            limit=settings.security_rate_limit_per_minute,
            window_seconds=60,
        )
        if not rate.allowed:
            await record_threat_event(client_ip, category="rate_limit", path=path)
            return _deny(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests.",
                headers={"Retry-After": str(rate.retry_after_seconds)},
            )

        threat = _scan_request_surface(request)
        if threat is not None:
            score = await record_threat_event(
                client_ip,
                category=threat,
                path=path,
            )
            logger.warning(
                "Suspicious request from %s path=%s category=%s score=%s",
                client_ip,
                path,
                threat,
                score,
            )
            if score >= settings.security_auto_block_threat_score:
                await block_ip(
                    client_ip,
                    ttl_seconds=settings.security_ip_block_ttl_seconds,
                    reason=threat,
                )
                if settings.cloudflare_auto_ban_enabled:
                    await get_cloudflare_client().ban_ip(
                        client_ip,
                        reason=f"{threat} on {path}",
                    )
                return _deny(
                    status.HTTP_403_FORBIDDEN,
                    "Access temporarily blocked due to suspicious activity.",
                )
            return _deny(
                status.HTTP_400_BAD_REQUEST,
                "Request rejected by security policy.",
            )

        response = await call_next(request)
        if rate.remaining >= 0:
            response.headers["X-RateLimit-Remaining"] = str(rate.remaining)
        return response


def _scan_request_surface(request: Request) -> str | None:
    """Scan path + query string for SQL / prompt-injection probes."""

    candidates = [
        request.url.path,
        str(request.url.query or ""),
    ]
    for key, value in request.query_params.multi_items():
        candidates.append(key)
        candidates.append(value)
    user_agent = request.headers.get("user-agent", "")
    if user_agent:
        candidates.append(user_agent)

    for item in candidates:
        if not item:
            continue
        hit = scan_text_for_threats(item)
        if hit is not None:
            return hit
    return None


def _deny(
    status_code: int,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "detail": detail},
        headers=headers,
    )
