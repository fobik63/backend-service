"""Redis Redlock-style leadership for a single Celery Beat process (audit R3).

Operational primary control remains ``deploy.replicas: 1`` on the beat
service. This lock is defense-in-depth if a second beat is started by mistake.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import uuid
from typing import Any

logger = logging.getLogger(__name__)

BEAT_LOCK_KEY = "celery:beat:leader"
_DEFAULT_TTL_SECONDS = 30
_held_lock: Any | None = None


def _redis_url() -> str:
    from app.core.config import get_settings

    settings = get_settings()
    return settings.effective_celery_broker_url or settings.redis_url


def acquire_beat_leader_lock(
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    blocking_timeout: float = 5.0,
) -> bool:
    """Acquire a Redis lock so only one Beat scheduler runs the crontab.

    Returns True when this process is the leader (or locking is disabled /
    Redis is unavailable — fail-open so a lone beat still starts).
    """

    global _held_lock
    if os.environ.get("CELERY_BEAT_SKIP_REDIS_LOCK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        logger.info("Celery Beat Redis lock skipped via CELERY_BEAT_SKIP_REDIS_LOCK")
        return True

    try:
        import redis
    except ImportError:
        logger.warning("redis package missing; Beat lock disabled")
        return True

    try:
        client = redis.Redis.from_url(
            _redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        token = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        lock = client.lock(
            BEAT_LOCK_KEY,
            timeout=max(5, ttl_seconds),
            blocking_timeout=blocking_timeout,
        )
        # redis-py Lock is Redlock-compatible for a single Redis master.
        acquired = bool(lock.acquire(token=token))
        if not acquired:
            logger.error(
                "Celery Beat leadership lock busy (key=%s); refusing to start "
                "a second scheduler. Scale beat to replicas=1 or stop the other "
                "beat process.",
                BEAT_LOCK_KEY,
            )
            return False
        _held_lock = lock
        atexit.register(_release_beat_leader_lock)
        logger.info("Celery Beat acquired leadership lock key=%s", BEAT_LOCK_KEY)
        return True
    except Exception:
        # Fail-closed in production so a second beat cannot double-fire crons
        # when Redis is flapping. Dev/staging stay fail-open for local DX.
        try:
            from app.core.config import get_settings

            if get_settings().app_env == "production":
                logger.error(
                    "Celery Beat Redis leadership lock unavailable in production; "
                    "refusing to start (fail-closed).",
                    exc_info=True,
                )
                return False
        except Exception:
            logger.warning("Could not resolve app_env for Beat lock policy", exc_info=True)
        logger.warning(
            "Celery Beat could not acquire Redis leadership lock; starting anyway",
            exc_info=True,
        )
        return True


def _release_beat_leader_lock() -> None:
    global _held_lock
    lock = _held_lock
    _held_lock = None
    if lock is None:
        return
    try:
        lock.release()
    except Exception:
        logger.debug("Beat leadership lock release failed", exc_info=True)


def ensure_single_beat_or_exit() -> None:
    """Call from Beat process entry before the scheduler loop."""

    if not acquire_beat_leader_lock():
        raise SystemExit(
            "Another Celery Beat instance holds the Redis leadership lock. "
            "Keep a single beat container (replicas=1)."
        )
