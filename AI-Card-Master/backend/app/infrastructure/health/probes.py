"""Deep readiness probes for Postgres, Redis, and Celery workers.

Used by the isolated ``/readyz`` endpoint. Each check is intentionally
fast and never raises into the HTTP layer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import get_settings
from app.infrastructure.celery_app import celery_app
from app.infrastructure.redis import redis_healthcheck
from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# Ordered so ``failed_service`` reports the first critical dependency down.
_SERVICE_ORDER: tuple[str, ...] = ("postgres", "redis", "celery")

# Celery control ping must stay short — readiness should not block probes.
_CELERY_INSPECT_TIMEOUT_SECONDS = 1.0


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
