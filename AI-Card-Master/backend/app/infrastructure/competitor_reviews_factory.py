"""Composition root for TOP-N competitor low-rating reviews collection."""

from __future__ import annotations

from app.application.competitor_reviews_service import CompetitorReviewsCollectionService
from app.core.config import get_settings
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient
from app.infrastructure.stock_parser.proxy_pool import ProxyPool


def build_competitor_reviews_service() -> CompetitorReviewsCollectionService:
    """Wire Wildberries feedbacks client for analytics complaint-corpus handlers."""

    settings = get_settings()
    proxy_pool = ProxyPool.from_csv(
        settings.competitor_audit_proxy_urls or settings.stock_parser_proxy_urls
    )
    client = WildberriesDeepClient(
        card_base_url=settings.stock_parser_wb_card_base_url,
        content_base_url=settings.competitor_audit_wb_content_base_url,
        dest=settings.stock_parser_wb_dest,
        timeout_seconds=settings.competitor_audit_timeout_seconds,
        proxy_pool=proxy_pool,
        max_reviews=settings.competitor_audit_max_reviews,
        request_delay_min_seconds=settings.stock_parser_request_delay_min_seconds,
        request_delay_max_seconds=settings.stock_parser_request_delay_max_seconds,
    )
    return CompetitorReviewsCollectionService(client)
