"""Celery tasks for async 3D generation and OOM-isolated 360° video render."""

from __future__ import annotations

import gc
import logging
import signal
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

from app.core.config import get_settings
from app.domain.three_d_video import (
    RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS,
    RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS,
)
from app.infrastructure.celery_app import CELERY_THREE_D_HEAVY_QUEUE, celery_app
from app.infrastructure.three_d_factory import build_three_d_service
from app.infrastructure.three_d_video_factory import build_three_d_video_render_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Process-local pointer so SIGTERM / soft-kill handlers can fail+refund the
# in-flight video job before the worker child exits.
_active_video_lock = threading.Lock()
_active_video_task_id: str | None = None
_signal_handlers_installed = False


class ThreeDTaskBase(Task):
    """Retry policy for idempotent 3D mesh pipeline tasks."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


class ThreeDVideoRenderTaskBase(Task):
    """No autoretry for OOM / time-limit failures — fail + refund instead."""

    autoretry_for = ()
    acks_late = True
    # Redeliver after worker death so the orphaned-RENDERING path can refund.
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


def _set_active_video_task(video_task_id: str | None) -> None:
    global _active_video_task_id
    with _active_video_lock:
        _active_video_task_id = video_task_id


def _get_active_video_task() -> str | None:
    with _active_video_lock:
        return _active_video_task_id


def _fail_active_video_sync(error_detail: str) -> None:
    """Best-effort FAILED + coin refund from a signal / crash handler."""

    video_task_id = _get_active_video_task()
    if not video_task_id:
        return
    try:

        async def _task() -> None:
            async with SessionLocal() as session:
                service = build_three_d_video_render_service(session)
                await service.fail_and_refund(
                    video_task_id=UUID(video_task_id),
                    error_detail=error_detail,
                )

        _run_async(_task)
        logger.warning(
            "Marked video task FAILED and refunded coins after signal/crash "
            "video_task_id=%s detail=%s",
            video_task_id,
            error_detail[:200],
        )
    except Exception:
        logger.exception(
            "Failed to settle video task after signal/crash video_task_id=%s",
            video_task_id,
        )
    finally:
        _set_active_video_task(None)


def _install_video_render_signal_handlers() -> None:
    """Capture SIGTERM so OOM-adjacent kills can still refund held coins."""

    global _signal_handlers_installed
    if _signal_handlers_installed:
        return
    _signal_handlers_installed = True

    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum: int, frame: object | None) -> None:
        _fail_active_video_sync(
            "Worker received SIGTERM during 360° video render "
            "(possible OOM / deploy restart). Frozen coins refunded."
        )
        if callable(previous_sigterm):
            previous_sigterm(signum, frame)  # type: ignore[call-arg]
        elif previous_sigterm == signal.SIG_DFL:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.raise_signal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        # Signals can only be set from the main thread of each worker child.
        logger.debug("Could not install SIGTERM handler for video render", exc_info=True)


@celery_app.task(
    bind=True,
    base=ThreeDTaskBase,
    name="three_d.process_generation_task",
)
def process_3d_generation_task(self: Task, task_id: str) -> dict[str, Any]:
    """Hold coins, submit to the 3D engine, poll (or await webhook), finalize."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_three_d_service(session)
            if self.request.id:
                await service.attach_celery_task(
                    task_id=UUID(task_id),
                    celery_task_id=str(self.request.id),
                )
            result = await service.process_generation_task(UUID(task_id))
            logger.info(
                "3D generation finished task_id=%s status=%s",
                task_id,
                result.get("status"),
            )
            return result

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=ThreeDTaskBase,
    name="three_d.poll_active_tasks",
)
def poll_active_3d_tasks(self: Task) -> dict[str, Any]:
    """Beat: advance PROCESSING tasks (webhook mode / recovery)."""

    async def _task() -> dict[str, Any]:
        settings = get_settings()
        async with SessionLocal() as session:
            service = build_three_d_service(session)
            return await service.poll_active_tasks(
                limit=settings.three_d_poll_batch_size
            )

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=ThreeDVideoRenderTaskBase,
    name="three_d.render_360_video_task",
    queue=CELERY_THREE_D_HEAVY_QUEUE,
    soft_time_limit=RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS,
)
def render_360_video_task(self: Task, video_task_id: str) -> dict[str, Any]:
    """Render a 360° orbital video with OOM-oriented isolation guards.

    * Queue: ``three_d_heavy`` (never shares concurrency with card generation).
    * ``soft_time_limit=150`` / ``time_limit=180`` (hard).
    * ``gc.collect()`` after every job to release mesh/FFmpeg buffers.
    * Redis progress every N frames: ``{"stage": "rendering_frames", "progress": 45}``.
    * On MemoryError / SoftTimeLimit / SIGTERM / worker crash → FAILED + refund.
    """

    _install_video_render_signal_handlers()
    _set_active_video_task(video_task_id)
    try:

        async def _task() -> dict[str, Any]:
            async with SessionLocal() as session:
                service = build_three_d_video_render_service(session)
                if self.request.id:
                    await service.attach_celery_task(
                        video_task_id=UUID(video_task_id),
                        celery_task_id=str(self.request.id),
                    )
                try:
                    result = await service.process_render_task(UUID(video_task_id))
                except MemoryError as exc:
                    logger.error(
                        "OOM during 360° video render video_task_id=%s",
                        video_task_id,
                    )
                    return await service.fail_and_refund(
                        video_task_id=UUID(video_task_id),
                        error_detail=f"OutOfMemory: {exc}",
                    )
                except SoftTimeLimitExceeded:
                    logger.error(
                        "Soft time limit hit for 360° video render video_task_id=%s",
                        video_task_id,
                    )
                    return await service.fail_and_refund(
                        video_task_id=UUID(video_task_id),
                        error_detail=(
                            "SoftTimeLimitExceeded: render exceeded "
                            f"{RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS}s"
                        ),
                    )
                except TimeLimitExceeded:
                    logger.error(
                        "Hard time limit hit for 360° video render video_task_id=%s",
                        video_task_id,
                    )
                    return await service.fail_and_refund(
                        video_task_id=UUID(video_task_id),
                        error_detail=(
                            "TimeLimitExceeded: render exceeded "
                            f"{RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS}s"
                        ),
                    )
                logger.info(
                    "360° video render finished video_task_id=%s status=%s",
                    video_task_id,
                    result.get("status"),
                )
                return result

        return _run_async(_task)
    except MemoryError as exc:
        _fail_active_video_sync(f"OutOfMemory: {exc}")
        return {
            "video_task_id": video_task_id,
            "status": "FAILED",
            "error": f"OutOfMemory: {exc}",
        }
    except SoftTimeLimitExceeded:
        _fail_active_video_sync(
            "SoftTimeLimitExceeded during 360° video render. Frozen coins refunded."
        )
        return {
            "video_task_id": video_task_id,
            "status": "FAILED",
            "error": "SoftTimeLimitExceeded",
        }
    except TimeLimitExceeded:
        _fail_active_video_sync(
            "TimeLimitExceeded during 360° video render. Frozen coins refunded."
        )
        return {
            "video_task_id": video_task_id,
            "status": "FAILED",
            "error": "TimeLimitExceeded",
        }
    finally:
        _set_active_video_task(None)
        # Release mesh / VTK / FFmpeg buffers before the next concurrent job.
        gc.collect()
