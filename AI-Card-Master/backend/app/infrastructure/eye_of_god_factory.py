"""Composition root for parser ↔ «Глаз Бога» bridge."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.eye_of_god_bridge_service import (
    CeleryEyeOfGodTrigger,
    EyeOfGodBridgeService,
)
from app.core.config import get_settings
from app.domain.eye_of_god import SalesSpikeConfig
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.eye_of_god.sku_image_fetcher import SkuCardImageFetcher
from app.infrastructure.persistence.eye_of_god_repository import EyeOfGodRepository
from app.infrastructure.persistence.stock_parser_repository import StockParserRepository


def build_eye_of_god_bridge_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enqueue_trigger: bool = True,
    vision: Claude47VisionClient | None = None,
    images: SkuCardImageFetcher | None = None,
) -> EyeOfGodBridgeService:
    """Wire ports for stock-parser workers and Eye-of-God Celery tasks."""

    settings = get_settings()
    client = vision
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

    image_fetcher = images or SkuCardImageFetcher(
        timeout_seconds=settings.eye_of_god_image_timeout_seconds,
        max_bytes=settings.generation_max_upload_bytes,
    )

    spike_config = SalesSpikeConfig(
        recent_window_days=settings.eye_of_god_recent_window_days,
        baseline_window_days=settings.eye_of_god_baseline_window_days,
        min_growth_ratio=settings.eye_of_god_min_growth_ratio,
        min_baseline_daily_sales=settings.eye_of_god_min_baseline_daily_sales,
        min_recent_reliable_days=settings.eye_of_god_min_recent_reliable_days,
        cooldown_hours=settings.eye_of_god_cooldown_hours,
    )

    return EyeOfGodBridgeService(
        persistence=EyeOfGodRepository(db_session),
        stock_persistence=StockParserRepository(db_session),
        spike_config=spike_config,
        model_name=settings.claude_47_model,
        prefer_hour_utc=settings.stock_parser_beat_hour_utc,
        lookback_days=settings.eye_of_god_lookback_days,
        vision=client,
        images=image_fetcher,
        trigger=CeleryEyeOfGodTrigger() if enqueue_trigger else None,
        max_images=settings.eye_of_god_max_images,
    )
