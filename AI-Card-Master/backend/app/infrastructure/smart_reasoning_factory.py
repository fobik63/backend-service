"""Composition helpers for Smart Reasoning Routing & analytics cache."""

from __future__ import annotations

from functools import lru_cache

from app.application.smart_reasoning_router import SmartReasoningRouter
from app.core.config import Settings, get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache


@lru_cache(maxsize=1)
def get_smart_reasoning_router() -> SmartReasoningRouter:
    """Process-local router (Haiku / Opus / Ollama) from settings."""

    settings = get_settings()
    return SmartReasoningRouter(
        simple_model=settings.claude_35_haiku_model,
        deep_model=settings.claude_47_model,
        local_model=settings.ollama_model if settings.ollama_enabled else None,
    )


def resolve_claude_model(
    kind: ReasoningTaskKind,
    settings: Settings | None = None,
) -> str:
    """Resolve Claude/local model id for a factory / worker composition root.

    LOCAL-tier kinds require ``ollama_model``; callers that only want Anthropic
    should pass SIMPLE/DEEP kinds (existing factories unchanged).
    """

    cfg = settings or get_settings()
    local = cfg.ollama_model if cfg.ollama_enabled else None
    router = SmartReasoningRouter(
        simple_model=cfg.claude_35_haiku_model,
        deep_model=cfg.claude_47_model,
        local_model=local,
    )
    if router.tier_for(kind).value == "local" and not local:
        # Fall back to Haiku when Ollama is off so factories stay safe.
        return cfg.claude_35_haiku_model
    try:
        return router.model_for(kind)
    except ValueError:
        return cfg.claude_35_haiku_model


def build_analytics_cache() -> RedisClaudeStageCache:
    """Fail-open Redis adapter used for 24h Claude analytics caching."""

    return RedisClaudeStageCache()
