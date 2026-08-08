"""Isolated infrastructure monitoring probes (liveness / readiness / deep).

These routes are intentionally outside ``/api/v1`` so orchestrators
(Kubernetes, Docker, load balancers) can hit them without auth or API
versioning. Existing ``/health`` and ``/health/*`` endpoints are unchanged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.core.rate_limit import limiter
from app.infrastructure.health import check_deep_health, check_readiness

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


class DeepHealthOkResponse(BaseModel):
    """All deep dependencies answered (DB, Redis, S3, FFmpeg, Celery)."""

    status: str = Field(default="ok")
    checks: dict[str, bool] = Field(default_factory=dict)


class DeepHealthUnhealthyResponse(BaseModel):
    """Deep health failure with per-dependency flags."""

    status: str = Field(default="unhealthy")
    failed_service: str
    checks: dict[str, bool] = Field(default_factory=dict)


@router.get(
    "/healthz",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
@limiter.exempt
async def healthz() -> LivenessResponse:
    """Lightweight liveness: process is up and the event loop responds.

    For deep dependency checks use ``GET /healthz/deep`` (DB, Redis, S3, FFmpeg).
    """

    return LivenessResponse(status="ok")


@router.get(
    "/healthz/deep",
    response_model=DeepHealthOkResponse | DeepHealthUnhealthyResponse,
    responses={
        status.HTTP_200_OK: {"model": DeepHealthOkResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": DeepHealthUnhealthyResponse},
    },
    summary="Deep health check (DB, Redis, S3, FFmpeg, Celery)",
)
@limiter.exempt
async def healthz_deep(response: Response) -> DeepHealthOkResponse | DeepHealthUnhealthyResponse:
    """Production deep probe: Postgres, Redis, S3, FFmpeg, and Celery workers."""

    report = await check_deep_health()
    if report.healthy:
        return DeepHealthOkResponse(status="ok", checks=report.checks)

    failed = report.failed_service or "unknown"
    logger.warning(
        "Deep health probe unhealthy: failed_service=%s checks=%s",
        failed,
        report.checks,
    )
    response.status_code = _READINESS_UNHEALTHY_STATUS
    return DeepHealthUnhealthyResponse(
        status="unhealthy",
        failed_service=failed,
        checks=report.checks,
    )


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
