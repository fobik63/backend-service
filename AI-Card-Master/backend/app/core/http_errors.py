"""Shared HTTPException → JSON body shaping for API clients."""

from __future__ import annotations

from typing import Any

from starlette.exceptions import HTTPException


def shape_http_exception_body(exc: HTTPException) -> dict[str, Any]:
    """Build the standard error envelope; promote structured ``code`` fields."""

    content: dict[str, Any] = {
        "success": False,
        "detail": exc.detail,
    }
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        content["code"] = exc.detail["code"]
        if "message" in exc.detail:
            content["detail"] = exc.detail["message"]
        for key, value in exc.detail.items():
            if key in {"code", "message"}:
                continue
            content[key] = value
    return content
