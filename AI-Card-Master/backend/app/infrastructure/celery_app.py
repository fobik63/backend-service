"""Celery application configured for durable, idempotent generation tasks."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_card_master",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=[
        "app.workers.generation_tasks",
        "app.workers.winback_tasks",
        "app.workers.bulk_generation_tasks",
        "app.workers.smart_variant_tasks",
        "app.workers.claude_reasoning_tasks",
        "app.workers.visual_audit_tasks",
        "app.workers.oracle_tasks",
        "app.workers.ai_strategy_tasks",
        "app.workers.pain_analysis_tasks",
        "app.workers.ab_test_tasks",
        "app.workers.stock_parser_tasks",
        "app.workers.eye_of_god_tasks",
        "app.workers.competitor_audit_tasks",
        "app.workers.source_retention_tasks",
    ],
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
        "winback.scan_inactivity": {"queue": "winback"},
        "winback.notify_luxury_loft_updates": {"queue": "winback"},
        "bulk.unpack_and_enqueue": {"queue": "bulk"},
        "bulk.poll_active_batches": {"queue": "bulk"},
        "smart_variant.recolor_and_enqueue": {"queue": "smart_variant"},
        "smart_variant.poll_active_syncs": {"queue": "smart_variant"},
        "claude.run_chain_of_thought": {"queue": "claude.reasoning"},
        "claude.dispatch_outbox": {"queue": "claude.recovery"},
        "claude.recover_stalled": {"queue": "claude.recovery"},
        "claude.run_visual_audit": {"queue": "claude.reasoning"},
        "claude.run_oracle_prediction": {"queue": "claude.reasoning"},
        "claude.run_ai_strategy_plan": {"queue": "claude.reasoning"},
        "claude.run_pain_analysis": {"queue": "claude.reasoning"},
        "ab_test.generate_and_publish": {"queue": "ab_test"},
        "ab_test.poll_active_experiments": {"queue": "ab_test"},
        "ab_test.resolve_experiment": {"queue": "ab_test"},
        "stock_parser.dispatch_nightly": {"queue": "stock_parser"},
        "stock_parser.parse_sku": {"queue": "stock_parser"},
        "stock_parser.parse_batch": {"queue": "stock_parser"},
        "claude.run_eye_of_god_vision": {"queue": "claude.reasoning"},
        "analytics.run_competitor_audit": {"queue": "analytics.scrape"},
        "claude.run_competitor_deep_analysis": {"queue": "claude.reasoning"},
        "privacy.purge_expired_sources": {"queue": "privacy.retention"},
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
        "dispatch-claude-analysis-outbox": {
            "task": "claude.dispatch_outbox",
            "schedule": 2.0,
        },
        "recover-stalled-claude-analyses": {
            "task": "claude.recover_stalled",
            "schedule": 60.0,
        },
        "winback-scan-inactivity": {
            "task": "winback.scan_inactivity",
            "schedule": settings.winback_inactivity_scan_seconds,
        },
        "winback-notify-luxury-loft-updates": {
            "task": "winback.notify_luxury_loft_updates",
            "schedule": settings.winback_style_update_scan_seconds,
        },
        "bulk-poll-active-batches": {
            "task": "bulk.poll_active_batches",
            "schedule": settings.bulk_generation_poll_seconds,
        },
        "smart-variant-poll-active-syncs": {
            "task": "smart_variant.poll_active_syncs",
            "schedule": settings.smart_variant_poll_seconds,
        },
        "ab-test-poll-active-experiments": {
            "task": "ab_test.poll_active_experiments",
            "schedule": settings.ab_test_poll_seconds,
        },
        # Deep-night stock scrape — never touches the FastAPI event loop.
        "stock-parser-nightly-dispatch": {
            "task": "stock_parser.dispatch_nightly",
            "schedule": crontab(
                hour=settings.stock_parser_beat_hour_utc,
                minute=settings.stock_parser_beat_minute_utc,
            ),
        },
        # Zero-Knowledge: purge heavy ZIP/originals after retention window.
        "privacy-purge-expired-sources": {
            "task": "privacy.purge_expired_sources",
            "schedule": settings.source_retention_scan_seconds,
        },
    },
)

# --- Operator alerts: Celery task failures → Telegram with file:line ---


@task_failure.connect
def _notify_celery_task_failure(
    sender: object | None = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    einfo: object | None = None,
    **_kwargs: object,
) -> None:
    """Push Celery failures to Telegram (error_type + file:line)."""

    if exception is None:
        return
    try:
        from app.core.logging_config import configure_logging
        from app.services.telegram_alerts import (
            extract_error_location,
            notify_error_sync,
        )

        configure_logging()
        location = extract_error_location(exception)
        traceback_text = None
        if einfo is not None and hasattr(einfo, "traceback"):
            traceback_text = str(getattr(einfo, "traceback"))
        notify_error_sync(
            error_type=type(exception).__name__,
            message=str(exception),
            location=location,
            context={
                "source": "celery",
                "task": getattr(sender, "name", str(sender)),
                "task_id": task_id or "",
            },
            traceback_text=traceback_text,
        )
    except Exception:
        # Never break the worker because alerting failed.
        pass


__all__ = ["celery_app"]
