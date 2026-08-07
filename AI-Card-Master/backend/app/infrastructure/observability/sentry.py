"""Sentry SDK bootstrap with FastAPI integration and PII scrubbing.

Masks passwords, JWT/Bearer tokens, and API keys before events leave the
process. Init is a no-op when ``SENTRY_DSN`` is unset.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)

_MASK = "[Filtered]"

_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"access[_-]?token|refresh[_-]?token|jwt|bearer|credential|"
    r"private[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
# Compact JWT (header.payload.signature) or Bearer-prefixed tokens in strings.
_JWT_RE = re.compile(
    r"(?i)\b(?:bearer\s+)?("
    r"eyJ[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-&+=/]*"
    r")"
)
_API_KEY_VALUE_RE = re.compile(
    r"(?i)\b((?:sk|pk|api|key|token)[-_][A-Za-z0-9_\-]{8,})\b"
)


def scrub_sensitive_string(value: str) -> str:
    """Mask JWT/Bearer tokens and common API-key shaped substrings."""

    scrubbed = _JWT_RE.sub(_MASK, value)
    return _API_KEY_VALUE_RE.sub(_MASK, scrubbed)


def scrub_sensitive_data(value: Any, *, _key: str | None = None) -> Any:
    """Recursively mask sensitive keys and token-like string values."""

    if _key is not None and _SENSITIVE_KEY_RE.search(_key):
        return _MASK

    if isinstance(value, dict):
        return {
            str(k): scrub_sensitive_data(v, _key=str(k)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return scrub_sensitive_string(value)
    return value


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry ``before_send`` hook — strip PII from the outbound event."""

    del hint  # unused; kept for SDK signature compatibility
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = scrub_sensitive_data(headers)
        data = request.get("data")
        if data is not None:
            request["data"] = scrub_sensitive_data(data)
        query = request.get("query_string")
        if isinstance(query, str):
            request["query_string"] = scrub_sensitive_string(query)
        elif isinstance(query, (list, dict)):
            request["query_string"] = scrub_sensitive_data(query)
        cookies = request.get("cookies")
        if cookies is not None:
            request["cookies"] = scrub_sensitive_data(cookies)
        env = request.get("env")
        if isinstance(env, dict):
            request["env"] = scrub_sensitive_data(env)
        event["request"] = request

    for section in ("extra", "contexts", "tags"):
        section_data = event.get(section)
        if isinstance(section_data, dict):
            event[section] = scrub_sensitive_data(section_data)

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            breadcrumbs["values"] = scrub_sensitive_data(values)
            event["breadcrumbs"] = breadcrumbs
    elif isinstance(breadcrumbs, list):
        event["breadcrumbs"] = scrub_sensitive_data(breadcrumbs)

    user = event.get("user")
    if isinstance(user, dict):
        # Keep id for correlation; drop email/ip/username PII.
        event["user"] = {
            key: value
            for key, value in user.items()
            if key in {"id", "segment"}
        }

    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                if "value" in item and isinstance(item["value"], str):
                    item["value"] = scrub_sensitive_string(item["value"])

    message = event.get("message")
    if isinstance(message, str):
        event["message"] = scrub_sensitive_string(message)

    return event


def init_sentry(settings: Settings) -> bool:
    """Initialize Sentry for FastAPI. Returns True when DSN was applied."""

    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        logger.info("Sentry disabled: SENTRY_DSN is not configured")
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.app_env,
        release=settings.sentry_release or None,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        before_send=before_send,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    logger.info(
        "Sentry initialized (env=%s, traces_sample_rate=%.3f)",
        settings.app_env,
        settings.sentry_traces_sample_rate,
    )
    return True


def capture_unhandled_exception(
    exc: BaseException,
    *,
    user_id: str | None = None,
) -> None:
    """Forward an unhandled exception to Sentry when the SDK is active."""

    try:
        import sentry_sdk
    except ImportError:
        return
    if not sentry_sdk.is_initialized():
        return
    with sentry_sdk.new_scope() as scope:
        if user_id:
            scope.set_user({"id": user_id})
        sentry_sdk.capture_exception(exc)

