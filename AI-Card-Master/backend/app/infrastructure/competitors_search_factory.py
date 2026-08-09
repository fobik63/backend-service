"""Composition root for keyword-based WB competitor search."""

from __future__ import annotations

from app.application.competitors_search_service import CompetitorsSearchService
from app.core.config import get_settings
from app.infrastructure.competitor_audit.wb_discovery_client import (
    WildberriesCompetitorDiscovery,
)
from app.infrastructure.stock_parser.proxy_pool import ProxyPool


def build_competitors_search_service() -> CompetitorsSearchService:
    """Wire Wildberries search.wb.ru discovery client for HTTP handlers."""

    settings = get_settings()
    proxy_pool = ProxyPool.from_csv(
        settings.competitor_audit_proxy_urls or settings.stock_parser_proxy_urls
    )
    discovery = WildberriesCompetitorDiscovery(
        dest=settings.stock_parser_wb_dest,
        timeout_seconds=settings.competitor_audit_timeout_seconds,
        proxy_pool=proxy_pool,
        request_delay_min_seconds=settings.stock_parser_request_delay_min_seconds,
        request_delay_max_seconds=settings.stock_parser_request_delay_max_seconds,
    )
    return CompetitorsSearchService(discovery)
