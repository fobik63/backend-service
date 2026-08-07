"""Process-local asyncio runtime for Celery workers.

Celery tasks must not dispose shared Postgres/Redis/AI pools after every job.
A single event loop per worker process keeps async clients reusable until
``worker_process_shutdown``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the process-local event loop, creating it on first use."""

    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_worker_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Run an async factory on the worker's persistent event loop."""

    loop = get_worker_loop()
    return loop.run_until_complete(factory())


async def close_worker_resources() -> None:
    """Close shared async pools owned by this worker process."""

    from app.infrastructure.redis import close_redis_client, close_security_redis_client
    from app.models.database import engine
    from app.services.ai_engine import close_ai_engine
    from app.services.marketplace_text import close_marketplace_text_service

    await close_ai_engine()
    await close_marketplace_text_service()
    await close_security_redis_client()
    await close_redis_client()
    await engine.dispose()


def shutdown_worker_resources() -> None:
    """Sync entrypoint for Celery ``worker_process_shutdown``."""

    global _loop
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        loop.run_until_complete(close_worker_resources())
    except Exception:
        logger.exception("Worker resource shutdown failed")
    finally:
        try:
            loop.close()
        except Exception:
            logger.exception("Worker event loop close failed")
        _loop = None


__all__ = [
    "close_worker_resources",
    "get_worker_loop",
    "run_worker_async",
    "shutdown_worker_resources",
]
