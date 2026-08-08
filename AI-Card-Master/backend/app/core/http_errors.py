"""Shared HTTPException → JSON body shaping for API clients.

Legacy clients keep ``success`` / ``detail`` / top-level ``code``.
New clients can rely on the nested envelope::

    {"error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

from typing import Any

from starlette.exceptions import HTTPException


def shape_error_envelope(
    *,
    code: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build the standardized nested error object (plus optional extras)."""

    body: dict[str, Any] = {
        "error": {
            "code": str(code),
            "message": str(message),
        }
    }
    for key, value in extra.items():
        if value is not None:
            body[key] = value
    return body


def shape_http_exception_body(exc: HTTPException) -> dict[str, Any]:
    """Build the standard error envelope; promote structured ``code`` fields."""

    content: dict[str, Any] = {
        "success": False,
        "detail": exc.detail,
    }
    error_code: str = f"http_{exc.status_code}"
    error_message: str
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        content["code"] = exc.detail["code"]
        error_code = str(exc.detail["code"])
        if "message" in exc.detail:
            content["detail"] = exc.detail["message"]
            error_message = str(exc.detail["message"])
        else:
            error_message = str(exc.detail.get("detail", exc.detail))
        for key, value in exc.detail.items():
            if key in {"code", "message"}:
                continue
            content[key] = value
    elif isinstance(exc.detail, str):
        error_message = exc.detail
    else:
        error_message = str(exc.detail)

    # Nested envelope (production contract) — does not remove legacy fields.
    content["error"] = {
        "code": error_code,
        "message": error_message,
    }
    return content
