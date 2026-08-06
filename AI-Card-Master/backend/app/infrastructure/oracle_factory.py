"""Composition root for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.oracle_service import OracleService
from app.core.config import get_settings
from app.domain.oracle import OracleGapConfig
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.persistence.oracle_repository import OracleRepository


def build_oracle_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enrichment: Claude47VisionClient | None = None,
) -> OracleService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = enrichment
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
    )
