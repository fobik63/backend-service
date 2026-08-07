"""Middleware that stamps baseline security headers on every response."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.security_headers import apply_security_headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach HSTS / CSP / framing / MIME sniffing / referrer policy headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        apply_security_headers(response, path=request.url.path)
        return response
