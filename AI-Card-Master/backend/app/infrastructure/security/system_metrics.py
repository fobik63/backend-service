"""Host CPU / RAM sampling for Security & Status (plan §62)."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.domain.security_status import HostResourceMetrics

logger = logging.getLogger(__name__)


def _sample_sync() -> HostResourceMetrics:
    """Blocking sample; always run via ``asyncio.to_thread``."""

    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("psutil is not installed; host metrics unavailable")
        return HostResourceMetrics(
            cpu_percent=0.0,
            ram_percent=0.0,
            ram_used_mb=0.0,
            ram_total_mb=0.0,
        )

    # interval=None is non-blocking after the first priming call.
    cpu = float(psutil.cpu_percent(interval=None))
    mem = psutil.virtual_memory()
    return HostResourceMetrics(
        cpu_percent=round(cpu, 2),
        ram_percent=round(float(mem.percent), 2),
        ram_used_mb=round(float(mem.used) / (1024 * 1024), 2),
        ram_total_mb=round(float(mem.total) / (1024 * 1024), 2),
    )


@lru_cache(maxsize=1)
def _prime_cpu_counter() -> None:
    """Warm psutil CPU counters so the first live sample is meaningful."""

    try:
        import psutil  # type: ignore[import-untyped]

        psutil.cpu_percent(interval=None)
    except Exception:
        logger.debug("Failed to prime psutil CPU counter", exc_info=True)


class PsutilHostMetrics:
    """``HostMetricsPort`` implementation backed by psutil."""

    def __init__(self) -> None:
        _prime_cpu_counter()

    async def sample(self) -> HostResourceMetrics:
        return await asyncio.to_thread(_sample_sync)
