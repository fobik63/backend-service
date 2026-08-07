"""Request context + admin-access audit middleware (plan §81).

Assigns ``request_id``, captures IP / visitorId / User-Agent, measures
duration, and records ``admin.endpoint_access`` for ``/api/v1/admin`` hits.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.application.behavioral_rate_limit_service import normalize_visitor_id
from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings
from app.core.request_context import (
    RequestAuditContext,
    clear_request_audit_context,
    new_request_id,
    set_request_audit_context,
)
from app.domain.audit_log import AuditEventStatus, AuditEventType

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Outermost-ish request identity for audit + future OpenTelemetry."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        header_name = settings.audit_request_id_header or "X-Request-Id"
        incoming = request.headers.get(header_name) or request.headers.get("x-request-id")
        request_id = (incoming or "").strip()[:64] or new_request_id()

        client_ip = getattr(request.state, "client_ip", None)
        if not client_ip:
            client_ip = resolve_client_ip(
                request,
                trust_cloudflare=settings.cloudflare_trust_headers,
                trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
            )
            request.state.client_ip = client_ip

        visitor_raw = request.headers.get("X-Visitor-Id") or request.headers.get(
            "x-visitor-id"
        )
        visitor_id = normalize_visitor_id(visitor_raw)
        user_agent = (request.headers.get("user-agent") or "")[:512] or None
        endpoint = request.url.path
        method = request.method

        request.state.request_id = request_id
        request.state.visitor_id = visitor_id
        request.state.user_agent = user_agent

        token = set_request_audit_context(
            RequestAuditContext(
                request_id=request_id,
                ip=client_ip,
                visitor_id=visitor_id,
                user_agent=user_agent,
                endpoint=endpoint,
                http_method=method,
            )
        )
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[header_name] = request_id
            return response
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            request.state.request_duration_ms = duration_ms
            try:
                if (
                    settings.audit_log_enabled
                    and settings.audit_log_admin_access_enabled
                    and endpoint.startswith("/api/v1/admin")
                ):
                    await self._record_admin_access(
                        request=request,
                        request_id=request_id,
                        client_ip=client_ip,
                        visitor_id=visitor_id,
                        user_agent=user_agent,
                        endpoint=endpoint,
                        method=method,
                        status_code=status_code,
                        duration_ms=duration_ms,
                    )
            except Exception:
                logger.debug("Admin access audit emit failed", exc_info=True)
            clear_request_audit_context()
            _ = token

    async def _record_admin_access(
        self,
        *,
        request: Request,
        request_id: str,
        client_ip: str | None,
        visitor_id: str | None,
        user_agent: str | None,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: int,
    ) -> None:
        from app.services.audit_events import record_audit_event

        if status_code >= 500:
            audit_status = AuditEventStatus.ERROR
        elif status_code in {401, 403}:
            audit_status = AuditEventStatus.DENIED
        elif status_code >= 400:
            audit_status = AuditEventStatus.FAILURE
        else:
            audit_status = AuditEventStatus.SUCCESS

        user_id = getattr(request.state, "audit_user_id", None)
        telegram_id = getattr(request.state, "audit_telegram_id", None)

        await record_audit_event(
            event_type=AuditEventType.ADMIN_ENDPOINT_ACCESS,
            status=audit_status,
            user_id=user_id,
            telegram_id=telegram_id,
            ip=client_ip,
            visitor_id=visitor_id,
            user_agent=user_agent,
            endpoint=endpoint,
            http_method=method,
            request_id=request_id,
            duration_ms=duration_ms,
            actor_type="admin",
            message=f"Admin endpoint {method} {endpoint} → {status_code}",
            metadata={"http_status": status_code},
        )
