"""Centralized logging configuration with Telegram ERROR notifications."""

from __future__ import annotations

import logging
import time
import traceback
from typing import ClassVar

from app.core.config import get_settings
from app.services.telegram_alerts import ErrorLocation, notify_error_sync


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

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    else:
        root.setLevel(level)

    # Attach Telegram handler once per process.
    already = any(isinstance(handler, TelegramErrorHandler) for handler in root.handlers)
    if not already and settings.telegram_error_logging_enabled:
        telegram_handler = TelegramErrorHandler(level=logging.ERROR)
        telegram_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        root.addHandler(telegram_handler)
