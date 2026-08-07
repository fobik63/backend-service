"""Shared security response headers applied to every HTTP response."""

from __future__ import annotations

from starlette.responses import Response

# Baseline network-level headers required on all API responses.
SECURITY_HEADER_VALUES: dict[str, str] = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

# Swagger / ReDoc load assets from a CDN; keep other headers, relax CSP only there.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data: https://cdn.jsdelivr.net"
)

_DOCS_PATH_PREFIXES = ("/docs", "/redoc")


def apply_security_headers(response: Response, *, path: str = "") -> None:
    """Set baseline security headers (setdefault so callers may override)."""

    for header, value in SECURITY_HEADER_VALUES.items():
        if header == "Content-Security-Policy" and any(
            path.startswith(prefix) for prefix in _DOCS_PATH_PREFIXES
        ):
            response.headers.setdefault(header, _DOCS_CSP)
            continue
        response.headers.setdefault(header, value)
