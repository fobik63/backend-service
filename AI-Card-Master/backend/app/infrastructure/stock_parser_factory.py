"""Composition root for the isolated stock-parser micro-module."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.stock_parser_service import StockParserService
from app.core.config import get_settings
from app.domain.stock_parser import ParserMarketplace
from app.infrastructure.persistence.stock_parser_repository import (
    StockParserRepository,
)
from app.infrastructure.stock_parser.ozon_mobile_client import OzonMobileClient
from app.infrastructure.stock_parser.proxy_pool import ProxyPool
from app.infrastructure.stock_parser.telegram_notifier import (
    StockParserTelegramNotifier,
)
from app.infrastructure.stock_parser.wildberries_mobile_client import (
    WildberriesMobileClient,
)


def build_stock_parser_service(db_session: AsyncSession) -> StockParserService:
    """Wire mobile JSON clients + proxy pool + health repo + Telegram alerts.

    Intentionally has no FastAPI dependencies — safe to call from Celery only.
    """

    settings = get_settings()
    proxy_pool = ProxyPool.from_csv(settings.stock_parser_proxy_urls)
    timeout = settings.stock_parser_timeout_seconds
    delay_min = settings.stock_parser_request_delay_min_seconds
    delay_max = settings.stock_parser_request_delay_max_seconds

    parsers = {
        ParserMarketplace.WILDBERRIES: WildberriesMobileClient(
            base_url=settings.stock_parser_wb_card_base_url,
            dest=settings.stock_parser_wb_dest,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
            request_delay_min_seconds=delay_min,
            request_delay_max_seconds=delay_max,
        ),
        ParserMarketplace.OZON: OzonMobileClient(
            base_url=settings.stock_parser_ozon_api_base_url,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
            request_delay_min_seconds=delay_min,
            request_delay_max_seconds=delay_max,
        ),
    }

    return StockParserService(
        StockParserRepository(db_session),
        parsers,
        alerts=StockParserTelegramNotifier(settings),
        circuit_breaker_threshold=settings.stock_parser_circuit_breaker_threshold,
    )
