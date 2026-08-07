"""Isolated infrastructure monitoring probes (liveness / readiness).

These routes are intentionally outside ``/api/v1`` so orchestrators
(Kubernetes, Docker, load balancers) can hit them without auth or API
versioning. Existing ``/health`` and ``/health/*`` endpoints are unchanged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.core.rate_limit import limiter
from app.infrastructure.health import check_readiness

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

# Non-standard but used by some CDN / ops stacks for origin dependency failure.
# Prefer 503 for broad client compatibility; both accepted by the contract.
_READINESS_UNHEALTHY_STATUS = status.HTTP_503_SERVICE_UNAVAILABLE


class LivenessResponse(BaseModel):
    """Minimal process-alive payload."""

    status: str = Field(default="ok", description="Always 'ok' when the process answers")


class ReadinessOkResponse(BaseModel):
    """All critical dependencies answered."""

    status: str = Field(default="ok", description="Ready to accept traffic")


class ReadinessUnhealthyResponse(BaseModel):
    """At least one dependency failed; ``failed_service`` names the first one."""

    status: str = Field(default="unhealthy", description="Not ready for traffic")
    failed_service: str = Field(
        ...,
        description="First failing dependency: postgres | redis | celery",
    )


@router.get(
    "/healthz",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
@limiter.exempt
async def healthz() -> LivenessResponse:
    """Lightweight liveness: process is up and the event loop responds."""

    return LivenessResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadinessOkResponse | ReadinessUnhealthyResponse,
    responses={
        status.HTTP_200_OK: {"model": ReadinessOkResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessUnhealthyResponse},
    },
    summary="Readiness probe",
)
@limiter.exempt
async def readyz(response: Response) -> ReadinessOkResponse | ReadinessUnhealthyResponse:
    """Deep readiness: Postgres ``SELECT 1``, Redis ``PING``, Celery workers."""

    report = await check_readiness()
    if report.healthy:
        return ReadinessOkResponse(status="ok")

    failed = report.failed_service or "unknown"
    logger.warning(
        "Readiness probe unhealthy: failed_service=%s checks=%s",
        failed,
        report.checks,
    )
    response.status_code = _READINESS_UNHEALTHY_STATUS
    return ReadinessUnhealthyResponse(status="unhealthy", failed_service=failed)
