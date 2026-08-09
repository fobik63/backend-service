"""Celery application configured for durable, idempotent generation tasks."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, worker_process_shutdown, worker_shutting_down

from app.core.config import get_settings

settings = get_settings()

_celery_includes = [
    "app.workers.generation_tasks",
    "app.workers.winback_tasks",
    "app.workers.bulk_generation_tasks",
    "app.workers.smart_variant_tasks",
    "app.workers.brand_lora_tasks",
    "app.workers.brand_dna_tasks",
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
    "app.workers.audit_log_tasks",
    "app.workers.orphan_cleanup_tasks",
]
if settings.enable_three_d:
    _celery_includes.append("app.workers.three_d_tasks")

celery_app = Celery(
    "ai_card_master",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=_celery_includes,
)

# Fast lane (cards/text/outbox) vs heavy 3D/GPU — never share a worker -Q list
# with three_d_heavy so long mesh jobs cannot starve interactive generation.
CELERY_DEFAULT_QUEUE = "default"
CELERY_THREE_D_HEAVY_QUEUE = "three_d_heavy"


def _three_d_video_soft_time_limit() -> int:
    return int(
        getattr(
            settings,
            "three_d_video_soft_time_limit_seconds",
            150,
        )
    )


def _three_d_video_hard_time_limit() -> int:
    return int(
        getattr(
            settings,
            "three_d_video_hard_time_limit_seconds",
            180,
        )
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
    task_default_queue=CELERY_DEFAULT_QUEUE,
    task_default_retry_delay=5,
    task_soft_time_limit=840,
    task_time_limit=900,
    result_expires=3600,
    task_always_eager=settings.celery_task_always_eager,
    task_store_eager_result=settings.celery_task_always_eager,
    task_routes={
        # Card / text generation — fast default lane (isolated from three_d_heavy).
        "generation.submit_job": {"queue": CELERY_DEFAULT_QUEUE},
        # Isolated low-priority queue for silently flagged abusers (no AI spend).
        "generation.submit_job_shadow": {
            "queue": "generation.shadow",
            "priority": 1,
        },
        "generation.process_webhook": {"queue": CELERY_DEFAULT_QUEUE},
        "generation.finalize_job": {"queue": CELERY_DEFAULT_QUEUE},
        "generation.dispatch_outbox": {"queue": CELERY_DEFAULT_QUEUE},
        "generation.recover_stalled": {"queue": CELERY_DEFAULT_QUEUE},
        "winback.scan_inactivity": {"queue": "winback"},
        "winback.notify_luxury_loft_updates": {"queue": "winback"},
        "bulk.unpack_and_enqueue": {"queue": "bulk"},
        "bulk.poll_active_batches": {"queue": "bulk"},
        "smart_variant.recolor_and_enqueue": {"queue": "smart_variant"},
        "smart_variant.poll_active_syncs": {"queue": "smart_variant"},
        "brand_lora.start_training": {"queue": "brand_lora"},
        "brand_lora.poll_active_trainings": {"queue": "brand_lora"},
        "brand_dna.refresh_for_user": {"queue": "brand_dna"},
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
        "audit.archive_old_events": {"queue": "privacy.retention"},
        "maintenance.cleanup_orphans": {"queue": "privacy.retention"},
        # Long-running 3D mesh / texture / video-render style jobs.
        "three_d.process_generation_task": {"queue": CELERY_THREE_D_HEAVY_QUEUE},
        "three_d.poll_active_tasks": {"queue": CELERY_THREE_D_HEAVY_QUEUE},
        "three_d.render_360_video_task": {
            "queue": CELERY_THREE_D_HEAVY_QUEUE,
            "soft_time_limit": _three_d_video_soft_time_limit(),
            "time_limit": _three_d_video_hard_time_limit(),
        },
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
        "brand-lora-poll-active-trainings": {
            "task": "brand_lora.poll_active_trainings",
            "schedule": settings.brand_lora_poll_seconds,
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
        # Enterprise audit: move aged rows from hot table → archive.
        "audit-archive-old-events": {
            "task": "audit.archive_old_events",
            "schedule": settings.audit_log_archive_scan_seconds,
        },
        # Orphaned Safe-Spend holds + local /tmp artefacts after worker crashes.
        "maintenance-cleanup-orphans": {
            "task": "maintenance.cleanup_orphans",
            "schedule": settings.orphan_cleanup_scan_seconds,
        },
        **(
            {
                "three-d-poll-active-tasks": {
                    "task": "three_d.poll_active_tasks",
                    "schedule": settings.three_d_poll_seconds,
                    "options": {"queue": CELERY_THREE_D_HEAVY_QUEUE},
                },
            }
            if settings.enable_three_d
            else {}
        ),
    },
)

# --- Worker lifecycle: close shared pools once per process, not per task ---


@worker_process_shutdown.connect
def _shutdown_worker_shared_resources(**_kwargs: object) -> None:
    """Dispose Postgres/Redis/AI clients when the worker child process exits."""

    from app.workers.async_runtime import shutdown_worker_resources

    shutdown_worker_resources()


@worker_shutting_down.connect
def _on_worker_shutting_down(sig: object = None, how: object = None, **_kwargs: object) -> None:
    """Graceful shutdown: settle in-flight billable work before process death.

    Video render registers a process-local active task id; we fail+refund it
    immediately. Broader orphaned HELD holds are swept by
    ``maintenance.cleanup_orphans`` after the age threshold.
    """

    import logging

    log = logging.getLogger(__name__)
    log.warning("Celery worker shutting down sig=%s how=%s — settling active work", sig, how)
    try:
        if settings.enable_three_d:
            from app.workers.three_d_tasks import fail_active_video_on_shutdown

            fail_active_video_on_shutdown(
                error_detail=f"Worker graceful shutdown (sig={sig}, how={how})"
            )
    except Exception:
        log.exception("Graceful shutdown settlement failed")


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
            traceback_text = str(einfo.traceback)
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


__all__ = [
    "CELERY_DEFAULT_QUEUE",
    "CELERY_THREE_D_HEAVY_QUEUE",
    "celery_app",
]


def _install_beat_leadership_hook() -> None:
    """Acquire Redis leadership lock when the Beat process boots (audit R3)."""

    try:
        from celery.signals import beat_init
    except ImportError:
        return

    @beat_init.connect
    def _on_beat_init(**_kwargs: object) -> None:
        from app.infrastructure.celery_beat_lock import ensure_single_beat_or_exit

        ensure_single_beat_or_exit()


_install_beat_leadership_hook()
