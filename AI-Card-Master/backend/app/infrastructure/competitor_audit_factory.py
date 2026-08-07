"""Composition root for manual competitor-link audit + Claude deep analysis."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.competitor_audit_service import (
    CeleryCompetitorDeepAnalysisTrigger,
    CompetitorAuditService,
)
from app.application.zero_hallucination_service import ZeroHallucinationService
from app.core.config import get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache
from app.infrastructure.competitor_audit.deep_scraper import CompetitorDeepScraper
from app.infrastructure.competitor_audit.image_fetcher import CompetitorCardImageFetcher
from app.infrastructure.competitor_audit.ozon_deep_client import OzonDeepClient
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient
from app.infrastructure.persistence.competitor_audit_repository import (
    CompetitorAuditRepository,
)
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)
from app.infrastructure.stock_parser.proxy_pool import ProxyPool


def build_competitor_audit_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    enqueue_analysis: bool = True,
    with_scraper: bool = True,
) -> CompetitorAuditService:
    """Wire deep scrapers + Claude Vision for HTTP handlers and Celery workers.

    Intentionally has no FastAPI dependencies — safe to call from Celery.

    * ``enqueue_analysis`` — scrape worker publishes Claude task after scrape.
    * ``require_claude_client`` — analysis worker must have Anthropic credentials.
    * ``with_scraper`` — analysis-only worker can skip marketplace HTTP clients.
    """

    settings = get_settings()
    proxy_pool = ProxyPool.from_csv(
        settings.competitor_audit_proxy_urls or settings.stock_parser_proxy_urls
    )
    timeout = settings.competitor_audit_timeout_seconds
    max_reviews = settings.competitor_audit_max_reviews

    if with_scraper:
        scraper: Any = CompetitorDeepScraper(
            wildberries=WildberriesDeepClient(
                card_base_url=settings.stock_parser_wb_card_base_url,
                content_base_url=settings.competitor_audit_wb_content_base_url,
                dest=settings.stock_parser_wb_dest,
                timeout_seconds=timeout,
                proxy_pool=proxy_pool,
                max_reviews=max_reviews,
            ),
            ozon=OzonDeepClient(
                base_url=settings.stock_parser_ozon_api_base_url,
                timeout_seconds=timeout,
                proxy_pool=proxy_pool,
                max_reviews=max_reviews,
            ),
        )
    else:
        scraper = _NoopScraper()

    analyzer = _build_claude_analyzer(
        settings,
        require_claude_client=require_claude_client,
    )

    images = CompetitorCardImageFetcher(
        timeout_seconds=settings.competitor_audit_image_timeout_seconds,
        max_bytes=settings.generation_max_upload_bytes,
    )

    # Reuse the same Claude client for OCR dual-check (plan §57); service does
    # not own/close it — CompetitorAuditService.aclose closes the analyzer.
    cross_check = ZeroHallucinationService(
        analyzer,
        enabled=settings.zero_hallucination_enabled,
        max_vision_images=settings.zero_hallucination_max_vision_images,
    )

    from app.infrastructure.token_governor_factory import (
        build_competitor_snapshot_store,
        build_token_governor,
    )

    return CompetitorAuditService(
        CompetitorAuditRepository(db_session),
        scraper=scraper,
        redis_raw_ttl_seconds=settings.competitor_audit_redis_ttl_seconds,
        analyzer=analyzer,
        images=images,
        analysis_trigger=(
            CeleryCompetitorDeepAnalysisTrigger() if enqueue_analysis else None
        ),
        model_name=resolve_claude_model(ReasoningTaskKind.COMPETITOR_AUDIT, settings),
        max_vision_images=settings.competitor_audit_max_vision_images,
        stage_cache=RedisClaudeStageCache(),
        cross_check=cross_check,
        token_governor=build_token_governor(settings),
        snapshot_store=build_competitor_snapshot_store(),
        snapshot_ttl_seconds=settings.token_governor_snapshot_ttl_seconds,
    )


def _build_claude_analyzer(settings: Any, *, require_claude_client: bool) -> Any | None:
    """Lazy-import Claude client so API enqueue/poll works without anthropic SDK."""

    from app.infrastructure.claude.facades import wrap_claude_for_domain

    task = ReasoningTaskKind.COMPETITOR_AUDIT
    client = load_claude_client(
        settings,
        require=require_claude_client,
        model_name=resolve_claude_model(task, settings),
        analytics_cache=build_analytics_cache(),
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )
    return wrap_claude_for_domain(client, domain="competitor_audit")


class _NoopScraper:
    """Placeholder scraper for analysis-only Celery workers."""

    async def scrape_card(self, link):  # noqa: ANN001
        raise RuntimeError("Scraper is not configured in this process.")

    async def aclose(self) -> None:
        return None
