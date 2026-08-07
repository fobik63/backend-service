"""Lazy Claude client loader for composition roots (batch boundary).

Factories must never import ``app.infrastructure.claude.client`` at module top
level: that pulls the optional ``anthropic`` SDK into every ``app.api`` import
and Celery worker bootstrap (including stock-parser-only processes).
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


def load_claude_client(
    settings: Any,
    *,
    require: bool = False,
    existing: T | None = None,
    model_name: str | None = None,
    analytics_cache: Any | None = None,
    analytics_cache_ttl_seconds: int | None = None,
    analytics_task_kind: str | None = None,
) -> T | Any | None:
    """Return a Claude47VisionClient, or None when SDK/credentials are absent.

    * ``existing`` — caller-injected fake/client (tests / workers).
    * ``require`` — raise ImportError / ClaudeConfigurationError instead of None.
    * ``model_name`` — Smart Routing override (Haiku vs Opus).
    * ``analytics_cache`` — optional 24h content-addressed Redis cache.
    """

    if existing is not None:
        return existing

    try:
        from app.infrastructure.claude.client import (
            Claude47VisionClient,
            ClaudeConfigurationError,
        )
    except ImportError:
        if require:
            raise
        return None

    def _build() -> Any:
        return Claude47VisionClient(
            settings,
            model_name=model_name,
            analytics_cache=analytics_cache,
            analytics_cache_ttl_seconds=analytics_cache_ttl_seconds,
            analytics_task_kind=analytics_task_kind,
        )

    if require:
        return _build()

    try:
        api_key = settings.claude_47_api_key
        if api_key and api_key.get_secret_value().strip():
            return _build()
    except ClaudeConfigurationError:
        return None
    return None
