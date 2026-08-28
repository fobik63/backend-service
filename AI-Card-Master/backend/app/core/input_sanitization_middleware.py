"""Middleware that sanitizes JSON / multipart request bodies for SQL / XSS / prompt probes."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from starlette.types import Message

from app.core.config import Settings, get_settings
from app.core.input_sanitization import InputSanitizationError, sanitize_payload

logger = logging.getLogger(__name__)

_JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})
_SKIP_PREFIXES = (
    "/health",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/images/upload",
    "/api/v1/webhooks/",
    "/api/v1/billing/webhook/",
    "/api/v1/payments/webhook",
)


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Validate JSON and multipart text fields for SQL / XSS / prompt probes.

    Binary file parts are skipped; provider webhooks stay unsigned-body.
    Path/query scanning is handled by SuspiciousActivityMiddleware (Great Wall).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.security_input_sanitization_enabled:
            return await call_next(request)

        path = request.url.path
        if request.method not in _JSON_METHODS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        content_type = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in content_type:
            return await _sanitize_multipart(request, call_next, settings)
        if "application/json" not in content_type:
            return await call_next(request)

        max_bytes = settings.security_max_json_body_bytes
        body = await request.body()
        if len(body) > max_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "success": False,
                    "detail": "Request body exceeds security size limit.",
                },
            )
        if not body:
            return await call_next(request)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            # Let FastAPI/Pydantic return a normal 422 later.
            return await _replay(request, body, call_next)

        rejected = _reject_if_unsafe(payload, settings=settings, method=request.method, path=path)
        if rejected is not None:
            return rejected

        return await _replay(request, body, call_next)


def _reject_if_unsafe(
    payload: object,
    *,
    settings: Settings,
    method: str,
    path: str,
) -> JSONResponse | None:
    try:
        sanitize_payload(
            payload,
            check_sql=True,
            check_xss=settings.security_xss_protection_enabled,
            check_prompt=settings.security_reject_prompt_injection,
        )
    except InputSanitizationError as exc:
        logger.warning(
            "Input sanitization rejected %s %s (%s)",
            method,
            path,
            exc.category,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "detail": "Request rejected by input sanitization policy.",
                "category": exc.category,
            },
        )
    return None


async def _sanitize_multipart(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    settings: Settings,
) -> Response:
    """Scan textual form fields; leave file parts untouched."""

    body = await request.body()
    if not body:
        return await call_next(request)

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    parsed = StarletteRequest(request.scope, receive)
    parsed.state._state = request.state._state  # noqa: SLF001
    try:
        form = await parsed.form()
    except MultiPartException:
        return await _replay(request, body, call_next)

    try:
        for _key, value in form.multi_items():
            if isinstance(value, UploadFile):
                continue
            if not isinstance(value, str):
                continue
            rejected = _reject_if_unsafe(
                value,
                settings=settings,
                method=request.method,
                path=request.url.path,
            )
            if rejected is not None:
                return rejected
    finally:
        await form.close()

    return await _replay(request, body, call_next)


async def _replay(
    request: Request,
    body: bytes,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Re-inject the consumed body so downstream handlers can read it."""

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    rebuilt = StarletteRequest(request.scope, receive)
    # Preserve state set by outer middleware (e.g. client_ip).
    rebuilt.state._state = request.state._state  # noqa: SLF001
    return await call_next(rebuilt)
