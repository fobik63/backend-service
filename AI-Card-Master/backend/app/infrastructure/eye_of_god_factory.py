"""Composition root for parser ↔ «Глаз Бога» bridge."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.eye_of_god_bridge_service import (
    CeleryEyeOfGodTrigger,
    EyeOfGodBridgeService,
)
from app.core.config import get_settings
from app.domain.eye_of_god import SalesSpikeConfig
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude.facades import wrap_claude_for_domain
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.eye_of_god.sku_image_fetcher import SkuCardImageFetcher
from app.infrastructure.persistence.eye_of_god_repository import EyeOfGodRepository
from app.infrastructure.persistence.stock_parser_repository import StockParserRepository
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)


def build_eye_of_god_bridge_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enqueue_trigger: bool = True,
    vision: Any | None = None,
    images: SkuCardImageFetcher | None = None,
) -> EyeOfGodBridgeService:
    """Wire ports for stock-parser workers and Eye-of-God Celery tasks.

    Plan §55: deep «Глаз Бога» analysis always routes to Claude 4.7 Opus and
    caches Vision analytics in Redis for 24h.
    """

    settings = get_settings()
    task = ReasoningTaskKind.EYE_OF_GOD
    model_name = resolve_claude_model(task, settings)
    analytics_cache = build_analytics_cache()
    client = load_claude_client(
        settings,
        require=require_claude_client,
        existing=vision,
        model_name=model_name,
        analytics_cache=analytics_cache,
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )
    vision_port = wrap_claude_for_domain(client, domain="eye_of_god")

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
        model_name=model_name,
        prefer_hour_utc=settings.stock_parser_beat_hour_utc,
        lookback_days=settings.eye_of_god_lookback_days,
        vision=vision_port if vision_port is not None else vision,
        images=image_fetcher,
        trigger=CeleryEyeOfGodTrigger() if enqueue_trigger else None,
        max_images=settings.eye_of_god_max_images,
        stage_cache=RedisClaudeStageCache(),
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
    )
