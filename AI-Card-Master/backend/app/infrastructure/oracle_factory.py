"""Composition root for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.oracle_service import OracleService
from app.core.config import get_settings
from app.domain.oracle import OracleGapConfig
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.oracle_repository import OracleRepository


def build_oracle_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enrichment: Any | None = None,
) -> OracleService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=enrichment,
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
        model_name=settings.claude_47_model,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        default_gap_config=gap_config,
        enrichment=client,
        stage_cache=RedisClaudeStageCache(),
    )
