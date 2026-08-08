"""Centralized logging configuration with Telegram ERROR notifications.

Supports plain-text (dev) and JSON structured logs (prod aggregators) with
``request_id`` / ``correlation_id`` injected from request ContextVars and
propagated into Celery workers via task headers when available.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.core.config import get_settings
from app.services.telegram_alerts import ErrorLocation, notify_error_sync


class RequestIdLogFilter(logging.Filter):
    """Attach ``request_id`` from ContextVar (or Celery task header) onto records."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = "-"
        try:
            from app.core.request_context import get_request_audit_context

            ctx = get_request_audit_context()
            if ctx is not None and ctx.request_id:
                request_id = ctx.request_id
        except Exception:
            pass
        if request_id == "-":
            try:
                from celery import current_task

                task = current_task
                if task is not None and getattr(task, "request", None) is not None:
                    headers = getattr(task.request, "headers", None) or {}
                    rid = headers.get("request_id") or headers.get("correlation_id")
                    if rid:
                        request_id = str(rid)[:64]
                    elif getattr(task.request, "id", None):
                        request_id = f"celery:{task.request.id}"
            except Exception:
                pass
        record.request_id = request_id  # type: ignore[attr-defined]
        record.correlation_id = request_id  # type: ignore[attr-defined]
        return True


class JsonLogFormatter(logging.Formatter):
    """One-line JSON log records for ELK / Loki / CloudWatch."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        # Extra fields commonly attached by call sites.
        for key in ("task_id", "user_id", "job_id", "endpoint"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class TelegramErrorHandler(logging.Handler):
    """Forward ERROR+ log records to Telegram with file:line + error_type.

    Rate-limited per (logger, file, line, error_type) to avoid alert storms.
    """

    _last_sent: ClassVar[dict[str, float]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        # Avoid recursive alerts when Telegram itself fails.
        if record.name.startswith("app.services.telegram_alerts"):
            return

        settings = get_settings()
        if not settings.telegram_error_logging_enabled:
            return
        token = (
            settings.telegram_error_bot_token.get_secret_value().strip()
            if settings.telegram_error_bot_token is not None
            else ""
        )
        chat_id = (settings.telegram_error_chat_id or "").strip()
        if not token or not chat_id:
            return

        error_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else record.levelname
        location = ErrorLocation(
            filename=record.pathname or "unknown",
            lineno=int(record.lineno or 0),
            func_name=record.funcName or "unknown",
        )
        dedupe_key = (
            f"{record.name}|{location.short_filename}|{location.lineno}|{error_type}"
        )
        now = time.monotonic()
        cooldown = settings.telegram_error_alert_cooldown_seconds
        last = self._last_sent.get(dedupe_key, 0.0)
        if now - last < cooldown:
            return
        self._last_sent[dedupe_key] = now

        traceback_text: str | None = None
        if record.exc_info:
            traceback_text = "".join(traceback.format_exception(*record.exc_info))

        try:
            notify_error_sync(
                error_type=error_type,
                message=record.getMessage(),
                location=location,
                context={
                    "logger": record.name,
                    "level": record.levelname,
                    "request_id": getattr(record, "request_id", "-"),
                },
                traceback_text=traceback_text,
            )
        except Exception:
            # Never raise from a logging handler.
            self.handleError(record)


def configure_logging() -> None:
    """Install root logging format and optional Telegram ERROR handler."""

    settings = get_settings()
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = bool(getattr(settings, "log_json_enabled", False))

    root = logging.getLogger()
    request_filter = RequestIdLogFilter()

    if not root.handlers:
        handler = logging.StreamHandler()
        if use_json:
            handler.setFormatter(JsonLogFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(name)s | rid=%(request_id)s | %(message)s"
                )
            )
        handler.addFilter(request_filter)
        root.addHandler(handler)
        root.setLevel(level)
    else:
        root.setLevel(level)
        # Ensure existing handlers carry request_id (idempotent reconfigure).
        for handler in root.handlers:
            if not any(isinstance(f, RequestIdLogFilter) for f in handler.filters):
                handler.addFilter(request_filter)
            if use_json and not isinstance(handler.formatter, JsonLogFormatter):
                # Keep Telegram handler on plain format; swap stream handlers only.
                if not isinstance(handler, TelegramErrorHandler):
                    handler.setFormatter(JsonLogFormatter())

    # Attach Telegram handler once per process.
    already = any(isinstance(handler, TelegramErrorHandler) for handler in root.handlers)
    if not already and settings.telegram_error_logging_enabled:
        telegram_handler = TelegramErrorHandler(level=logging.ERROR)
        telegram_handler.addFilter(request_filter)
        telegram_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        root.addHandler(telegram_handler)
