"""Composition root for competitor negative-review pain analysis."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.pain_analysis_service import PainAnalysisService
from app.core.config import get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude.facades import wrap_claude_for_domain
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.pain_analysis_repository import (
    PainAnalysisRepository,
)
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)
from app.infrastructure.token_governor_factory import (
    build_token_governor,
    load_ollama_client,
)


def build_pain_analysis_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    analyzer: Any | None = None,
) -> PainAnalysisService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    task = ReasoningTaskKind.PAIN_ANALYSIS
    model_name = resolve_claude_model(task, settings)
    analytics_cache = build_analytics_cache()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=analyzer,
        model_name=model_name,
        analytics_cache=analytics_cache,
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )
    # A3: inject domain façade, not the god-client, into the use case.
    facade = wrap_claude_for_domain(client, domain="pain_analysis")
    local_llm = load_ollama_client(settings)

    return PainAnalysisService(
        PainAnalysisRepository(db_session),
        model_name=model_name,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        analyzer=facade if facade is not None else analyzer,
        stage_cache=RedisClaudeStageCache(),
        token_governor=build_token_governor(settings),
        local_llm=local_llm,
    )
