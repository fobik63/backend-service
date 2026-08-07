"""Great Wall middleware: rate-limit, XSS/SQL scan, auto-ban, Cloudflare + Telegram.

Extends the plan §14 suspicious-activity gate with plan §61 capabilities:
- Redis rate limits by client IP and by API-key / bearer fingerprint
- Auto IP (and API-key) ban when the request budget is exceeded
- Cloudflare Firewall Access Rule push for edge blocks
- One Telegram alert per ban window to the operator chat
"""

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
    RateLimitDecision,
    SecurityControlUnavailableError,
    block_api_key,
    block_ip,
    claim_ban_alert_slot,
    check_api_key_rate_limit,
    check_rate_limit,
    extract_api_key_credential,
    fingerprint_api_key,
    is_api_key_blocked,
    is_ip_blocked,
    record_request_for_rps,
    record_threat_event,
    append_blocked_threat,
    should_fail_closed_on_redis,
)
from app.services.telegram_alerts import notify_security_ban

logger = logging.getLogger(__name__)


class SuspiciousActivityMiddleware(BaseHTTPMiddleware):
    """Rate-limit, score, and optionally auto-ban abusive clients (Great Wall)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.security_suspicious_middleware_enabled:
            return await call_next(request)

        path = request.url.path
        if path in {"/", "/health", "/health/live", "/healthz", "/health/ready"}:
            return await call_next(request)
        if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
            return await call_next(request)

        client_ip = resolve_client_ip(
            request,
            trust_cloudflare=settings.cloudflare_trust_headers,
            trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
        )
        request.state.client_ip = client_ip

        raw_api_key = extract_api_key_credential(request)
        api_key_fp = fingerprint_api_key(raw_api_key) if raw_api_key else None
        if api_key_fp is not None:
            request.state.api_key_fingerprint = api_key_fp

        fail_closed = should_fail_closed_on_redis(path)
        try:
            if await is_ip_blocked(client_ip, fail_closed=fail_closed):
                return _deny(
                    status.HTTP_403_FORBIDDEN,
                    "Access temporarily blocked due to suspicious activity.",
                )
            if api_key_fp is not None and await is_api_key_blocked(
                api_key_fp,
                fail_closed=fail_closed,
            ):
                return _deny(
                    status.HTTP_403_FORBIDDEN,
                    "API key temporarily blocked due to suspicious activity.",
                )
        except SecurityControlUnavailableError as exc:
            return _security_unavailable(exc)

        await record_request_for_rps()

        silent_ban_enabled = bool(getattr(settings, "silent_ban_enabled", True))
        flagged_ip = False
        if silent_ban_enabled:
            from app.infrastructure.security.silent_ban_store import RedisSilentBanStore

            flagged_ip = await RedisSilentBanStore().is_flagged_ip(ip=client_ip)

        if flagged_ip:
            ip_rate = await check_rate_limit(
                ip=client_ip,
                limit=int(getattr(settings, "silent_ban_flagged_ip_rate_limit", 1)),
                window_seconds=int(
                    getattr(settings, "silent_ban_flagged_ip_window_seconds", 300)
                ),
                path=path,
            )
            if not ip_rate.allowed:
                if ip_rate.redis_unavailable:
                    return _security_unavailable_from_decision(ip_rate)
                return await _handle_rate_limit_breach(
                    request=request,
                    client_ip=client_ip,
                    api_key_fp=api_key_fp,
                    path=path,
                    rate=ip_rate,
                    subject="ip",
                    auto_ban=False,
                )
        else:
            ip_rate = await check_rate_limit(
                ip=client_ip,
                limit=settings.security_rate_limit_per_minute,
                window_seconds=60,
                path=path,
            )
            if not ip_rate.allowed:
                if ip_rate.redis_unavailable:
                    return _security_unavailable_from_decision(ip_rate)
                return await _handle_rate_limit_breach(
                    request=request,
                    client_ip=client_ip,
                    api_key_fp=api_key_fp,
                    path=path,
                    rate=ip_rate,
                    subject="ip",
                )

        key_rate: RateLimitDecision | None = None
        if api_key_fp is not None and settings.security_api_key_rate_limit_per_minute > 0:
            key_rate = await check_api_key_rate_limit(
                api_key_fingerprint=api_key_fp,
                limit=settings.security_api_key_rate_limit_per_minute,
                window_seconds=60,
                path=path,
            )
            if not key_rate.allowed:
                if key_rate.redis_unavailable:
                    return _security_unavailable_from_decision(key_rate)
                return await _handle_rate_limit_breach(
                    request=request,
                    client_ip=client_ip,
                    api_key_fp=api_key_fp,
                    path=path,
                    rate=key_rate,
                    subject="api_key",
                )

        threat = _scan_request_surface(
            request,
            check_xss=settings.security_xss_protection_enabled,
        )
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
            from app.domain.audit_log import AuditEventStatus, AuditEventType
            from app.services.audit_events import record_audit_event

            await record_audit_event(
                event_type=AuditEventType.SECURITY_SUSPICIOUS,
                status=AuditEventStatus.DENIED,
                ip=client_ip,
                user_agent=(request.headers.get("user-agent") or "")[:512] or None,
                endpoint=path,
                http_method=request.method,
                actor_type="system",
                message=f"Suspicious request: {threat}",
                metadata={"category": threat, "score": score},
            )
            if score >= settings.security_auto_block_threat_score:
                await _auto_ban(
                    client_ip=client_ip,
                    api_key_fp=api_key_fp,
                    path=path,
                    reason=threat,
                    ban_api_key=False,
                )
                await append_blocked_threat(
                    ip=client_ip,
                    category=threat,
                    path=path,
                    action="banned",
                    http_status=status.HTTP_403_FORBIDDEN,
                    score=score,
                    api_key_fingerprint=api_key_fp,
                )
                return _deny(
                    status.HTTP_403_FORBIDDEN,
                    "Access temporarily blocked due to suspicious activity.",
                )
            await append_blocked_threat(
                ip=client_ip,
                category=threat,
                path=path,
                action="denied",
                http_status=status.HTTP_400_BAD_REQUEST,
                score=score,
                api_key_fingerprint=api_key_fp,
            )
            return _deny(
                status.HTTP_400_BAD_REQUEST,
                "Request rejected by security policy.",
            )

        response = await call_next(request)
        remaining = ip_rate.remaining
        if key_rate is not None and key_rate.remaining >= 0:
            remaining = min(remaining, key_rate.remaining)
        if remaining >= 0:
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


async def _handle_rate_limit_breach(
    *,
    request: Request,
    client_ip: str,
    api_key_fp: str | None,
    path: str,
    rate: RateLimitDecision,
    subject: str,
    auto_ban: bool = True,
) -> JSONResponse:
    """Record the excess, optionally auto-ban, and return HTTP 429."""

    settings = get_settings()
    category = f"rate_limit_{subject}"
    await record_threat_event(client_ip, category=category, path=path)

    banned = False
    if auto_ban and settings.security_rate_limit_auto_ban_enabled:
        await _auto_ban(
            client_ip=client_ip,
            api_key_fp=api_key_fp,
            path=path,
            reason=category,
            ban_api_key=subject == "api_key",
        )
        banned = True

    await append_blocked_threat(
        ip=client_ip,
        category=category,
        path=path,
        action="banned" if banned else "rate_limited",
        http_status=status.HTTP_429_TOO_MANY_REQUESTS,
        api_key_fingerprint=api_key_fp,
    )

    from app.domain.audit_log import AuditEventStatus, AuditEventType
    from app.services.audit_events import record_audit_event

    await record_audit_event(
        event_type=AuditEventType.SECURITY_ERROR,
        status=AuditEventStatus.DENIED,
        ip=client_ip,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        endpoint=path,
        http_method=request.method,
        actor_type="system",
        message=f"Rate limit breached ({subject})",
        metadata={
            "category": category,
            "banned": banned,
            "subject": subject,
            "retry_after_seconds": rate.retry_after_seconds,
        },
    )

    headers = {"Retry-After": str(rate.retry_after_seconds)}
    detail = (
        "API key rate limit exceeded."
        if subject == "api_key"
        else "Too many requests."
    )
    return _deny(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail,
        headers=headers,
    )


async def _auto_ban(
    *,
    client_ip: str,
    api_key_fp: str | None,
    path: str,
    reason: str,
    ban_api_key: bool,
) -> None:
    """Redis ban + optional Cloudflare edge ban + Telegram operator alert."""

    settings = get_settings()
    ttl = settings.security_ip_block_ttl_seconds
    await block_ip(client_ip, ttl_seconds=ttl, reason=reason)
    if ban_api_key and api_key_fp is not None:
        await block_api_key(api_key_fp, ttl_seconds=ttl, reason=reason)

    cloudflare_banned = False
    if settings.cloudflare_auto_ban_enabled:
        cloudflare_banned = await get_cloudflare_client().ban_ip(
            client_ip,
            reason=f"{reason} on {path}",
        )

    if not settings.security_telegram_ban_alerts_enabled:
        return

    alert_subject = f"ip:{client_ip}"
    if not await claim_ban_alert_slot(alert_subject, ttl_seconds=ttl):
        return

    await notify_security_ban(
        ip=client_ip,
        reason=reason,
        path=path,
        ttl_seconds=ttl,
        cloudflare_banned=cloudflare_banned,
        api_key_fingerprint=api_key_fp,
    )


def _scan_request_surface(
    request: Request,
    *,
    check_xss: bool,
) -> str | None:
    """Scan path + query string for SQL / XSS / prompt-injection probes."""

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
        hit = scan_text_for_threats(item, check_xss=check_xss)
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


def _security_unavailable(exc: SecurityControlUnavailableError) -> JSONResponse:
    return _deny(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        exc.message,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _security_unavailable_from_decision(rate: RateLimitDecision) -> JSONResponse:
    return _deny(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Security controls temporarily unavailable.",
        headers={"Retry-After": str(max(rate.retry_after_seconds, 1))},
    )
