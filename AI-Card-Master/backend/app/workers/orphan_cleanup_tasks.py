"""Celery beat: refund orphaned coin holds and purge stale local temp files."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from celery import Task
from sqlalchemy import select

from app.core.config import get_settings
from app.core.pricing import BillingService as PricingBillingService
from app.core.pricing import CoinHoldStatus
from app.infrastructure.celery_app import celery_app
from app.models.coin_hold import CoinHold
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")

_TEMP_PREFIXES = ("series_zip_", "series_zip_bytes_", "ai-card-master")


class OrphanCleanupTask(Task):
    """Retry policy for idempotent orphan / temp sweeps."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    return run_worker_async(factory)


def _purge_stale_temp_dirs(*, max_age_hours: int) -> int:
    """Delete aged directories under the process temp root (best-effort)."""

    root = Path(tempfile.gettempdir())
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0

    candidates: list[Path] = []
    # Project-scoped mesh / render cache.
    mesh_cache = root / "ai-card-master"
    if mesh_cache.is_dir():
        candidates.append(mesh_cache)
        candidates.extend(p for p in mesh_cache.iterdir() if p.is_dir() or p.is_file())

    try:
        for entry in root.iterdir():
            name = entry.name
            if any(name.startswith(prefix) for prefix in _TEMP_PREFIXES):
                candidates.append(entry)
    except OSError:
        logger.debug("Temp root listing failed", exc_info=True)

    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove temp path %s", path, exc_info=True)
    return removed


async def _refund_orphaned_holds(*, max_age_hours: int, limit: int = 100) -> int:
    """Mark aged HELD coin_holds as refunded and restore balances."""

    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    refunded = 0
    async with SessionLocal() as session:
        holds = list(
            await session.scalars(
                select(CoinHold)
                .where(
                    CoinHold.status == CoinHoldStatus.HELD.value,
                    CoinHold.created_at < cutoff,
                )
                .order_by(CoinHold.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        if not holds:
            return 0

        pricing = PricingBillingService(session)
        for hold in holds:
            try:
                await pricing.commit_or_refund(
                    UUID(str(hold.id)),
                    success=False,
                    commit=False,
                )
                refunded += 1
            except Exception:
                logger.exception(
                    "Orphan hold refund failed hold_id=%s user_id=%s",
                    hold.id,
                    hold.user_id,
                )
        await session.commit()
    return refunded


@celery_app.task(
    bind=True,
    base=OrphanCleanupTask,
    name="maintenance.cleanup_orphans",
)
def cleanup_orphans_task(self: Task) -> dict[str, int]:
    """Periodic sweep: orphaned Safe-Spend holds + local temp artefacts."""

    settings = get_settings()

    async def _task() -> dict[str, int]:
        holds_refunded = await _refund_orphaned_holds(
            max_age_hours=settings.orphan_coin_hold_max_age_hours,
        )
        temps_removed = await asyncio.to_thread(
            _purge_stale_temp_dirs,
            max_age_hours=settings.orphan_temp_max_age_hours,
        )
        logger.info(
            "Orphan cleanup done holds_refunded=%s temps_removed=%s",
            holds_refunded,
            temps_removed,
        )
        return {
            "holds_refunded": int(holds_refunded),
            "temps_removed": int(temps_removed),
        }

    return _run_async(_task)


__all__ = ["cleanup_orphans_task"]
