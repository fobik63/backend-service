"""Composition root for Claude 4.7 Vision & Reasoning (API + Celery)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.claude_reasoning_service import ClaudeReasoningService
from app.core.config import get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.persistence.claude_reasoning_repository import (
    ClaudeReasoningRepository,
)
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)
from app.services.s3_storage import get_s3_storage


def build_claude_reasoning_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    claude: Any | None = None,
) -> ClaudeReasoningService:
    """Wire ports for HTTP handlers and Celery workers.

    API enqueue/status can omit the live Anthropic client; Celery workers
    must set ``require_claude_client=True``.
    """

    settings = get_settings()
    task = ReasoningTaskKind.CLAUDE_REASONING
    model_name = resolve_claude_model(task, settings)
    analytics_cache = build_analytics_cache()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=claude,
        model_name=model_name,
        analytics_cache=analytics_cache,
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )

    return ClaudeReasoningService(
        ClaudeReasoningRepository(db_session),
        storage=get_s3_storage(),
        model_name=model_name,
        max_images=settings.claude_47_max_images_per_request,
        max_image_bytes=settings.generation_max_upload_bytes,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        processing_timeout_seconds=settings.claude_47_processing_timeout_seconds,
        claude=client,
        stage_cache=RedisClaudeStageCache(),
    )
