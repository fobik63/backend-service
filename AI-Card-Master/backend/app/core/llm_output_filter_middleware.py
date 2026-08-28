"""Middleware that strips LLM responses containing canary / system-prompt leaks."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.prompt_safety import LLM_OUTPUT_BLOCKED_STUB, llm_output_contains_leak

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = (
    "/health",
    "/healthz",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/webhooks/",
    "/api/v1/billing/webhook/",
    "/api/v1/payments/webhook",
)
_DROP_HEADERS = frozenset({"content-length", "content-type"})


class LlmOutputFilterMiddleware(BaseHTTPMiddleware):
    """Scan JSON responses; replace leaked system-prompt fragments with a stub."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)
        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if not llm_output_contains_leak(body):
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() != "content-length"
            }
            replay = Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
                background=response.background,
            )
            return replay

        logger.warning(
            "LLM output filter blocked %s %s",
            request.method,
            path,
        )
        passthrough = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in _DROP_HEADERS
        }
        stub = JSONResponse(
            content=LLM_OUTPUT_BLOCKED_STUB,
            status_code=200,
            headers=passthrough,
        )
        stub.background = response.background
        return stub
