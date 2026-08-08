"""Middleware that rejects oversized request bodies early (HTTP 413)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from starlette.types import Message

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Methods that normally carry a body we should size-check.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Explicit image / multipart upload surfaces → SECURITY_MAX_UPLOAD_PAYLOAD_BYTES.
_IMAGE_UPLOAD_PREFIXES = (
    "/api/v1/images/upload",
    "/api/v1/generations",
    "/api/v1/smart-variants",
    "/api/v1/claude-reasoning",
    "/api/v1/claude-analyses",
    "/api/v1/brand-loras",
    "/api/v1/brand-dna",
    "/api/v1/visual-audit",
    "/api/v1/tools/remove-bg",
)

_BULK_UPLOAD_PREFIX = "/api/v1/bulk-generations"

# Prefer the non-deprecated Starlette alias when available.
_HTTP_413 = int(getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413))


class PayloadSizeLimiterMiddleware(BaseHTTPMiddleware):
    """Enforce Content-Length + actual body size limits before handlers run.

    Default ceiling is 5 MiB. Image upload routes allow 10 MiB. Bulk ZIP and
    generation multipart keep their feature-specific ceilings so existing
    upload contracts are not broken.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.security_payload_size_limiter_enabled:
            return await call_next(request)

        if request.method not in _BODY_METHODS:
            return await call_next(request)

        max_bytes = _resolve_max_bytes(request.url.path, settings)
        content_length = _parse_content_length(request.headers.get("content-length"))
        if content_length is not None and content_length > max_bytes:
            return _too_large(max_bytes)

        # No body declared — pass through without buffering.
        if content_length == 0:
            return await call_next(request)

        body = await request.body()
        if len(body) > max_bytes:
            logger.warning(
                "Rejected oversized body on %s %s (limit=%s, actual=%s)",
                request.method,
                request.url.path,
                max_bytes,
                len(body),
            )
            return _too_large(max_bytes)

        if not body:
            return await call_next(request)

        return await _replay(request, body, call_next)


def _resolve_max_bytes(path: str, settings: Settings) -> int:
    """Pick the tightest applicable ceiling for this route."""

    if path.startswith(_BULK_UPLOAD_PREFIX):
        return settings.bulk_generation_max_zip_bytes
    if any(path.startswith(prefix) for prefix in _IMAGE_UPLOAD_PREFIXES):
        # Generation multipart historically allows up to GENERATION_MAX_UPLOAD_BYTES;
        # never tighten below the feature limit for those routes.
        if path.startswith("/api/v1/generations"):
            return max(
                settings.security_max_upload_payload_bytes,
                settings.generation_max_upload_bytes,
            )
        return settings.security_max_upload_payload_bytes
    return settings.security_max_payload_bytes


def _parse_content_length(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _too_large(max_bytes: int) -> JSONResponse:
    return JSONResponse(
        status_code=_HTTP_413,
        content={
            "success": False,
            "detail": "Payload Too Large",
            "max_bytes": max_bytes,
        },
    )


async def _replay(
    request: Request,
    body: bytes,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Re-inject the consumed body so downstream middleware/handlers can read it."""

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    rebuilt = StarletteRequest(request.scope, receive)
    rebuilt.state._state = request.state._state  # noqa: SLF001
    return await call_next(rebuilt)
