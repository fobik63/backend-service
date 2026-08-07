"""Composition root for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai_strategy_service import StrategyService
from app.core.config import get_settings
from app.domain.ai_strategy import StrategyCompareConfig
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.ai_strategy_repository import AiStrategyRepository


def build_ai_strategy_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    planning: Any | None = None,
) -> StrategyService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=planning,
    )

    compare_config = StrategyCompareConfig(
        min_ctr_lift_pct=settings.ai_strategy_min_ctr_lift_pct,
        min_absolute_ctr_gap=settings.ai_strategy_min_absolute_ctr_gap,
        max_recommendations=settings.ai_strategy_max_recommendations,
        require_leader_ctr_advantage=settings.ai_strategy_require_leader_ctr_advantage,
    )

    return StrategyService(
        AiStrategyRepository(db_session),
        model_name=settings.claude_47_model,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        default_compare_config=compare_config,
        planning=client,
        stage_cache=RedisClaudeStageCache(),
    )
