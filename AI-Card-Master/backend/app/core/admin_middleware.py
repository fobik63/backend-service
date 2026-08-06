"""Strict middleware gate for hidden admin endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_and_validate_token


class AdminOnlyMiddleware(BaseHTTPMiddleware):
    """Allow /api/v1/admin only for the configured operator user id."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/api/v1/admin"):
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        settings = get_settings()
        allowed_user_id = settings.admin_allowed_user_id.strip()
        if not allowed_user_id:
            return _admin_error(
                status.HTTP_403_FORBIDDEN,
                "Admin API is disabled.",
            )

        try:
            UUID(allowed_user_id)
        except ValueError:
            return _admin_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Admin API is misconfigured.",
            )

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return _admin_error(
                status.HTTP_401_UNAUTHORIZED,
                "Admin authentication token is required.",
                authenticate=True,
            )

        try:
            payload = decode_and_validate_token(token.strip(), expected_type="access")
        except InvalidTokenError:
            return _admin_error(
                status.HTTP_401_UNAUTHORIZED,
                "Invalid or expired access token.",
                authenticate=True,
            )

        subject = str(payload.get("sub") or "").strip()
        if subject != allowed_user_id:
            return _admin_error(
                status.HTTP_403_FORBIDDEN,
                "Access denied.",
            )

        request.state.admin_user_id = subject
        return await call_next(request)


def _admin_error(
    status_code: int,
    detail: str,
    *,
    authenticate: bool = False,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "detail": detail},
        headers=headers,
    )
