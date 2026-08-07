"""Composition root for competitor negative-review pain analysis."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.pain_analysis_service import PainAnalysisService
from app.core.config import get_settings
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.pain_analysis_repository import (
    PainAnalysisRepository,
)


def build_pain_analysis_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    analyzer: Any | None = None,
) -> PainAnalysisService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=analyzer,
    )

    return PainAnalysisService(
        PainAnalysisRepository(db_session),
        model_name=settings.claude_47_model,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        analyzer=client,
        stage_cache=RedisClaudeStageCache(),
    )
