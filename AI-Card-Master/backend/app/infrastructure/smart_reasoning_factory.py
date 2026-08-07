"""Composition helpers for Smart Reasoning Routing & analytics cache."""

from __future__ import annotations

from functools import lru_cache

from app.application.smart_reasoning_router import SmartReasoningRouter
from app.core.config import Settings, get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache


@lru_cache(maxsize=1)
def get_smart_reasoning_router() -> SmartReasoningRouter:
    """Process-local router (Haiku vs Opus) from settings."""

    settings = get_settings()
    return SmartReasoningRouter(
        simple_model=settings.claude_35_haiku_model,
        deep_model=settings.claude_47_model,
    )


def resolve_claude_model(
    kind: ReasoningTaskKind,
    settings: Settings | None = None,
) -> str:
    """Resolve Claude model id for a factory / worker composition root."""

    cfg = settings or get_settings()
    return SmartReasoningRouter(
        simple_model=cfg.claude_35_haiku_model,
        deep_model=cfg.claude_47_model,
    ).model_for(kind)


def build_analytics_cache() -> RedisClaudeStageCache:
    """Fail-open Redis adapter used for 24h Claude analytics caching."""

    return RedisClaudeStageCache()
