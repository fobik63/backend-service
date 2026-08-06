"""Composition root for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai_strategy_service import StrategyService
from app.core.config import get_settings
from app.domain.ai_strategy import StrategyCompareConfig
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.persistence.ai_strategy_repository import AiStrategyRepository


def build_ai_strategy_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    planning: Claude47VisionClient | None = None,
) -> StrategyService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = planning
    if client is None and require_claude_client:
        client = Claude47VisionClient(settings)
    elif client is None:
        try:
            if (
                settings.claude_47_api_key
                and settings.claude_47_api_key.get_secret_value().strip()
            ):
                client = Claude47VisionClient(settings)
        except ClaudeConfigurationError:
            client = None

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
    )
