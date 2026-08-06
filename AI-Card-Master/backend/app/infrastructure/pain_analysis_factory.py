"""Composition root for competitor negative-review pain analysis."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.pain_analysis_service import PainAnalysisService
from app.core.config import get_settings
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.persistence.pain_analysis_repository import (
    PainAnalysisRepository,
)


def build_pain_analysis_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    analyzer: Claude47VisionClient | None = None,
) -> PainAnalysisService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = analyzer
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

    return PainAnalysisService(
        PainAnalysisRepository(db_session),
        model_name=settings.claude_47_model,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        analyzer=client,
    )
