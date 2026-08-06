"""Composition root for Claude 4.7 intelligent visual audit."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.visual_audit_service import VisualAuditService
from app.core.config import get_settings
from app.domain.visual_audit import VisualAuditFilterConfig
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.persistence.visual_audit_repository import VisualAuditRepository
from app.services.s3_storage import get_s3_storage


def build_visual_audit_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    vision: Claude47VisionClient | None = None,
) -> VisualAuditService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = vision
    if client is None and require_claude_client:
        client = Claude47VisionClient(settings)
    elif client is None:
        try:
            if settings.claude_47_api_key and settings.claude_47_api_key.get_secret_value().strip():
                client = Claude47VisionClient(settings)
        except ClaudeConfigurationError:
            client = None

    filter_config = VisualAuditFilterConfig(
        top_n=settings.visual_audit_top_n,
        brand_dominant_soft_reviews=settings.visual_audit_brand_dominant_soft_reviews,
        brand_dominant_hard_reviews=settings.visual_audit_brand_dominant_hard_reviews,
        rising_min_reviews=settings.visual_audit_rising_min_reviews,
        rising_max_reviews=settings.visual_audit_rising_max_reviews,
        min_sales_growth_ratio=settings.visual_audit_min_sales_growth_ratio,
        min_review_velocity_per_day=settings.visual_audit_min_review_velocity_per_day,
        max_rising_stars_for_vision=settings.visual_audit_max_rising_stars_for_vision,
    )

    return VisualAuditService(
        VisualAuditRepository(db_session),
        storage=get_s3_storage(),
        model_name=settings.claude_47_model,
        max_image_bytes=settings.generation_max_upload_bytes,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        default_filter_config=filter_config,
        vision=client,
    )
