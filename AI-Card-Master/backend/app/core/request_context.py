"""Request-scoped context for Enterprise Audit Log (plan §81).

Uses ``contextvars`` so application/services can attach IP / visitorId /
request_id without depending on FastAPI ``Request``. Future OTel spans can
read the same context.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RequestAuditContext:
    request_id: str
    ip: str | None = None
    visitor_id: str | None = None
    user_agent: str | None = None
    endpoint: str | None = None
    http_method: str | None = None
    user_id: str | None = None
    telegram_id: int | None = None


_request_audit_ctx: ContextVar[RequestAuditContext | None] = ContextVar(
    "request_audit_ctx",
    default=None,
)


def new_request_id() -> str:
    return str(uuid4())


def get_request_audit_context() -> RequestAuditContext | None:
    return _request_audit_ctx.get()


def set_request_audit_context(ctx: RequestAuditContext) -> Token[RequestAuditContext | None]:
    return _request_audit_ctx.set(ctx)


def reset_request_audit_context(token: Token[RequestAuditContext | None]) -> None:
    _request_audit_ctx.reset(token)


def clear_request_audit_context() -> None:
    _request_audit_ctx.set(None)


def merge_context_into_kwargs(**explicit: Any) -> dict[str, Any]:
    """Fill missing audit fields from the current request context."""

    ctx = get_request_audit_context()
    if ctx is None:
        return {k: v for k, v in explicit.items() if v is not None}

    merged = {
        "request_id": explicit.get("request_id") or ctx.request_id,
        "ip": explicit.get("ip") if explicit.get("ip") is not None else ctx.ip,
        "visitor_id": (
            explicit.get("visitor_id")
            if explicit.get("visitor_id") is not None
            else ctx.visitor_id
        ),
        "user_agent": (
            explicit.get("user_agent")
            if explicit.get("user_agent") is not None
            else ctx.user_agent
        ),
        "endpoint": (
            explicit.get("endpoint") if explicit.get("endpoint") is not None else ctx.endpoint
        ),
        "http_method": (
            explicit.get("http_method")
            if explicit.get("http_method") is not None
            else ctx.http_method
        ),
    }
    for key, value in explicit.items():
        if key in merged:
            continue
        if value is not None:
            merged[key] = value
    return merged
