"""Composition root for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.oracle_service import OracleService
from app.core.config import get_settings
from app.domain.oracle import OracleGapConfig
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude.facades import wrap_claude_for_domain
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.oracle_repository import OracleRepository
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)


def build_oracle_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enrichment: Any | None = None,
) -> OracleService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    task = ReasoningTaskKind.ORACLE_ENRICHMENT
    model_name = resolve_claude_model(task, settings)
    analytics_cache = build_analytics_cache()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=enrichment,
        model_name=model_name,
        analytics_cache=analytics_cache,
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )

    gap_config = OracleGapConfig(
        min_query_growth_ratio=settings.oracle_min_query_growth_ratio,
        min_recent_query_volume=settings.oracle_min_recent_query_volume,
        max_top_cards_for_gap=settings.oracle_max_top_cards_for_gap,
        min_gap_score=settings.oracle_min_gap_score,
        max_alerts=settings.oracle_max_alerts,
        top_rank_ceiling=settings.oracle_top_rank_ceiling,
    )

    return OracleService(
        OracleRepository(db_session),
        model_name=model_name,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        default_gap_config=gap_config,
        enrichment=wrap_claude_for_domain(client, domain="oracle") or enrichment,
        stage_cache=RedisClaudeStageCache(),
    )
