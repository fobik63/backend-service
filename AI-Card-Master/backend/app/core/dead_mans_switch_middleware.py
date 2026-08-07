"""Reject public traffic while Dead Man's Switch lockdown is active (plan §37)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.services.dead_mans_switch import get_dead_mans_switch

# Paths that remain reachable during lockdown (liveness + explicit unlock).
_ALWAYS_ALLOW_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/health/live",
        "/security/dead-mans-switch",
        "/security/dead-mans-switch/clear",
        "/security/dead-mans-switch/status",
    }
)


class DeadMansSwitchMiddleware(BaseHTTPMiddleware):
    """When lockdown is active, block non-VPN peers except allowlisted paths."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.dead_mans_switch_enabled:
            return await call_next(request)

        dms = get_dead_mans_switch()
        if not await dms.is_active():
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        # Normalize trailing slash variants for allowlist matching.
        allow_paths = {p.rstrip("/") or "/" for p in _ALWAYS_ALLOW_PATHS}
        peer = request.client.host if request.client is not None else None

        if path in allow_paths or dms.peer_is_vpn_allowlisted(peer):
            return await call_next(request)

        state = await dms.get_state()
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "code": "DEAD_MANS_SWITCH_ACTIVE",
                "detail": "External access blocked by Dead Man's Switch.",
                "triggered_at": state.triggered_at,
            },
            headers={"Retry-After": "3600"},
        )
