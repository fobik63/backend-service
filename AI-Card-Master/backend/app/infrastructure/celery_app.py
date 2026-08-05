"""Celery application configured for durable, idempotent generation tasks."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_card_master",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=["app.workers.generation_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=5,
    task_soft_time_limit=840,
    task_time_limit=900,
    result_expires=3600,
    task_always_eager=settings.celery_task_always_eager,
    task_store_eager_result=settings.celery_task_always_eager,
    task_routes={
        "generation.submit_job": {"queue": "generation.submit"},
        "generation.process_webhook": {"queue": "generation.finalize"},
        "generation.finalize_job": {"queue": "generation.finalize"},
        "generation.dispatch_outbox": {"queue": "generation.recovery"},
        "generation.recover_stalled": {"queue": "generation.recovery"},
    },
    beat_schedule={
        "dispatch-generation-outbox": {
            "task": "generation.dispatch_outbox",
            "schedule": 2.0,
        },
        "recover-stalled-generations": {
            "task": "generation.recover_stalled",
            "schedule": 60.0,
        },
    },
)

__all__ = ["celery_app"]
