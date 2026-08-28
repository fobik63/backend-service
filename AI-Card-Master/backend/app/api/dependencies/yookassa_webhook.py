"""FastAPI dependency: YooKassa webhook source IP allowlist."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from app.core.yookassa_webhook_ips import (
    is_allowed_yookassa_webhook_request,
    resolve_webhook_source_ip,
)
from app.services.billing_service import BillingNotFoundError

logger = logging.getLogger(__name__)

YOOKASSA_WEBHOOK_ACK_DETAIL = "Webhook accepted."


async def require_yookassa_webhook_source(request: Request) -> None:
    """Reject webhooks whose source IP is outside official YooKassa ranges."""

    if is_allowed_yookassa_webhook_request(request):
        return
    source_ip = (
        getattr(request.state, "client_ip", None)
        or resolve_webhook_source_ip(request)
        or (request.client.host if request.client is not None else "unknown")
    )
    logger.warning("Rejected YooKassa webhook from non-allowlisted IP %s", source_ip)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook source IP is not in the YooKassa allowlist.",
    )


def log_yookassa_webhook_failure(exc: BaseException, *, scope: str) -> None:
    """Record webhook processing errors; callers always acknowledge HTTP 200."""

    if isinstance(exc, BillingNotFoundError):
        logger.warning("%s YooKassa webhook for unknown payment: %s", scope, exc)
        return
    logger.exception("%s YooKassa webhook failed", scope)
