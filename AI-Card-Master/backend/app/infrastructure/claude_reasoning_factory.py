"""Composition root for Claude 4.7 Vision & Reasoning (API + Celery)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.claude_reasoning_service import ClaudeReasoningService
from app.core.config import get_settings
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.persistence.claude_reasoning_repository import (
    ClaudeReasoningRepository,
)
from app.services.s3_storage import get_s3_storage


def build_claude_reasoning_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    claude: Claude47VisionClient | None = None,
) -> ClaudeReasoningService:
    """Wire ports for HTTP handlers and Celery workers.

    API enqueue/status can omit the live Anthropic client; Celery workers
    must set ``require_claude_client=True``.
    """

    settings = get_settings()
    client = claude
    if client is None and require_claude_client:
        client = Claude47VisionClient(settings)
    elif client is None:
        # Best-effort: attach client when key is present so enqueue can
        # still validate configuration early in staging.
        try:
            if settings.claude_47_api_key and settings.claude_47_api_key.get_secret_value().strip():
                client = Claude47VisionClient(settings)
        except ClaudeConfigurationError:
            client = None

    return ClaudeReasoningService(
        ClaudeReasoningRepository(db_session),
        storage=get_s3_storage(),
        model_name=settings.claude_47_model,
        max_images=settings.claude_47_max_images_per_request,
        max_image_bytes=settings.generation_max_upload_bytes,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        claude=client,
    )
