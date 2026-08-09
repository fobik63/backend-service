"""Deep readiness probes for Postgres, Redis, Celery, S3, and FFmpeg.

Used by ``/readyz`` and ``/healthz/deep``. Each check is intentionally
fast and never raises into the HTTP layer.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.redis import redis_healthcheck
from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# Ordered so ``failed_service`` reports the first critical dependency down.
_SERVICE_ORDER: tuple[str, ...] = ("postgres", "redis", "celery")
_DEEP_SERVICE_ORDER: tuple[str, ...] = ("postgres", "redis", "s3", "ffmpeg", "celery")

# Celery control ping must stay short — readiness should not block probes.
_CELERY_INSPECT_TIMEOUT_SECONDS = 1.0
_FFMPEG_PROBE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregate readiness result for orchestration probes."""

    healthy: bool
    failed_service: str | None
    checks: dict[str, bool]


async def postgres_healthcheck() -> bool:
    """Return True when ``SELECT 1`` succeeds against Postgres."""

    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Postgres readiness check failed", exc_info=True)
        return False


def _celery_workers_ping_sync() -> bool:
    """Blocking Celery control.inspect().ping(); run via ``asyncio.to_thread``."""

    settings = get_settings()
    # In-process eager mode has no separate workers — treat as ready.
    if settings.celery_task_always_eager:
        return True

    try:
        inspector = celery_app.control.inspect(timeout=_CELERY_INSPECT_TIMEOUT_SECONDS)
        replies = inspector.ping()
    except Exception:
        logger.warning("Celery workers readiness check failed", exc_info=True)
        return False

    if not replies:
        logger.warning("Celery workers readiness check: no workers replied to ping")
        return False
    return True


async def celery_workers_healthcheck() -> bool:
    """Return True when at least one Celery worker responds to ping."""

    return await asyncio.to_thread(_celery_workers_ping_sync)


async def s3_healthcheck() -> bool:
    """Return True when the configured object store answers ``head_bucket``."""

    try:
        from app.services.s3_storage import get_s3_storage

        return bool(await get_s3_storage().healthcheck())
    except Exception:
        logger.warning("S3 readiness check failed", exc_info=True)
        return False


def _ffmpeg_probe_sync(ffmpeg_bin: str) -> bool:
    """Return True when ``ffmpeg -version`` exits 0 within a short timeout."""

    import subprocess

    resolved = shutil.which(ffmpeg_bin) or ffmpeg_bin
    try:
        completed = subprocess.run(
            [resolved, "-version"],
            check=False,
            capture_output=True,
            timeout=_FFMPEG_PROBE_TIMEOUT_SECONDS,
        )
        return completed.returncode == 0
    except Exception:
        logger.warning("FFmpeg readiness check failed bin=%s", resolved, exc_info=True)
        return False


async def ffmpeg_healthcheck() -> bool:
    """Return True when FFmpeg is on PATH / configured bin responds.

    When 3D is disabled, FFmpeg is treated as optional and reports healthy
    so non-3D deployments are not marked down.
    """

    settings = get_settings()
    if not getattr(settings, "enable_three_d", False):
        return True
    ffmpeg_bin = (getattr(settings, "three_d_ffmpeg_bin", None) or "ffmpeg").strip() or "ffmpeg"
    return await asyncio.to_thread(_ffmpeg_probe_sync, ffmpeg_bin)


async def check_readiness() -> ReadinessReport:
    """Run Postgres → Redis → Celery probes; report first failure."""

    checks: dict[str, bool] = {
        "postgres": await postgres_healthcheck(),
        "redis": await redis_healthcheck(),
        "celery": await celery_workers_healthcheck(),
    }
    failed_service: str | None = None
    for name in _SERVICE_ORDER:
        if not checks[name]:
            failed_service = name
            break
    return ReadinessReport(
        healthy=failed_service is None,
        failed_service=failed_service,
        checks=checks,
    )


async def check_deep_health() -> ReadinessReport:
    """Deep probe: Postgres, Redis, S3, FFmpeg, Celery."""

    checks: dict[str, bool] = {
        "postgres": await postgres_healthcheck(),
        "redis": await redis_healthcheck(),
        "s3": await s3_healthcheck(),
        "ffmpeg": await ffmpeg_healthcheck(),
        "celery": await celery_workers_healthcheck(),
    }
    failed_service: str | None = None
    for name in _DEEP_SERVICE_ORDER:
        if not checks[name]:
            failed_service = name
            break
    return ReadinessReport(
        healthy=failed_service is None,
        failed_service=failed_service,
        checks=checks,
    )
