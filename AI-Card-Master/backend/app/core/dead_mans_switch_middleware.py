"""Reject public traffic while Dead Man's Switch lockdown is active (plan §37).

Allowlist policy (coordinated with CloudflareProtectionMiddleware):
- Liveness probes always pass.
- Ingest endpoints (db-auth-failure / trigger) always pass so the host watchdog
  and admin panel can still raise the alarm during lockdown.
- Clear / status require a VPN-gateway peer (or loopback) — never public clear.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.services.dead_mans_switch import get_dead_mans_switch

# Always reachable during lockdown (probes + alarm ingest).
_ALWAYS_ALLOW_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/health/live",
        "/security/dead-mans-switch/db-auth-failure",
        "/security/dead-mans-switch/trigger",
    }
)

# Reachable only from VPN allowlist / loopback while lockdown is active.
_VPN_ONLY_PATHS: frozenset[str] = frozenset(
    {
        "/security/dead-mans-switch",
        "/security/dead-mans-switch/status",
        "/security/dead-mans-switch/clear",
    }
)


def _normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


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

        path = _normalize_path(request.url.path)
        always_allow = {_normalize_path(p) for p in _ALWAYS_ALLOW_PATHS}
        vpn_only = {_normalize_path(p) for p in _VPN_ONLY_PATHS}
        peer = request.client.host if request.client is not None else None
        vpn_ok = dms.peer_is_vpn_allowlisted(peer)

        if path in always_allow or vpn_ok:
            return await call_next(request)

        if path in vpn_only:
            # Explicit deny for public peers hitting unlock/status surfaces.
            state = await dms.get_state()
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "success": False,
                    "code": "DEAD_MANS_SWITCH_ACTIVE",
                    "detail": "Dead Man's Switch unlock requires VPN gateway.",
                    "triggered_at": state.triggered_at,
                },
                headers={"Retry-After": "3600"},
            )

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
