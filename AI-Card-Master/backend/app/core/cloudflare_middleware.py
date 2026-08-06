"""Cloudflare edge enforcement + baseline security response headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.client_ip import is_cloudflare_edge_ip, resolve_client_ip
from app.core.config import get_settings


class CloudflareProtectionMiddleware(BaseHTTPMiddleware):
    """When enabled, require traffic to arrive via Cloudflare and set headers.

    Combined with DNS proxied (orange-cloud) records and an origin firewall that
    only accepts Cloudflare IP ranges, this hides the real server IP from the
    public internet and mitigates volumetric DDoS at the edge.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        path = request.url.path

        if settings.cloudflare_enabled and settings.cloudflare_enforce_edge:
            if path not in {"/health", "/health/live"}:
                peer = request.client.host if request.client is not None else ""
                has_cf_ray = bool((request.headers.get("CF-Ray") or "").strip())
                has_cf_ip = bool((request.headers.get("CF-Connecting-IP") or "").strip())
                peer_is_cf = is_cloudflare_edge_ip(peer) if peer else False
                if settings.app_env == "production":
                    if not (peer_is_cf and has_cf_ray and has_cf_ip):
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={
                                "success": False,
                                "detail": "Direct origin access is forbidden.",
                            },
                        )
                elif settings.cloudflare_enforce_edge and peer and not peer_is_cf:
                    # Non-production: only warn via header; do not hard-block local dev.
                    pass

        if not hasattr(request.state, "client_ip"):
            request.state.client_ip = resolve_client_ip(
                request,
                trust_cloudflare=settings.cloudflare_trust_headers,
                trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
            )

        response = await call_next(request)
        _apply_security_headers(response, settings.app_env)
        if settings.cloudflare_enabled:
            response.headers.setdefault("CF-Edge-Aware", "1")
        return response


def _apply_security_headers(response: Response, app_env: str) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=()",
    )
    if app_env == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
