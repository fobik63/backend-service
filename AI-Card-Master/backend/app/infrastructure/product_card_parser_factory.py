"""Wire product-card fetch use case to deep scrapers, S3, and Redis."""

from __future__ import annotations

import logging
from typing import Any

from app.application.product_card_parser_service import ProductCardParserService
from app.core.config import Settings, get_settings
from app.domain.competitor_audit import CompetitorMarketplace
from app.domain.product_card_parser import REDIS_PRODUCT_CARD_TTL_SECONDS
from app.infrastructure.competitor_audit.image_fetcher import CompetitorCardImageFetcher
from app.infrastructure.competitor_audit.ozon_deep_client import OzonDeepClient
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)
from app.infrastructure.stock_parser.proxy_pool import ProxyPool
from app.services.s3_storage import SelectelS3Storage, get_s3_storage

logger = logging.getLogger(__name__)


class RedisProductCardCache:
    """Fail-open Redis JSON cache for ``/api/parser/fetch`` responses."""

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            return await get_cached_json(key)
        except RedisUnavailableError as exc:
            logger.warning("Product-card Redis get unavailable: %s", exc)
            return None

    async def set(
        self, key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        try:
            await cache_json(key, payload, ttl_seconds)
        except RedisUnavailableError as exc:
            logger.warning("Product-card Redis set unavailable: %s", exc)


class _LazyS3Storage:
    """Defer Selectel client construction until the first upload attempt."""

    def __init__(self, storage: SelectelS3Storage | None = None) -> None:
        self._storage = storage

    def _resolve(self) -> SelectelS3Storage:
        if self._storage is None:
            self._storage = get_s3_storage()
        return self._storage

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> Any:
        return await self._resolve().upload_bytes(
            object_key=object_key,
            data=data,
            content_type=content_type,
            presign=presign,
            cache_control=cache_control,
        )


def build_product_card_parser_service(
    *,
    settings: Settings | None = None,
    storage: SelectelS3Storage | None = None,
) -> ProductCardParserService:
    """Construct the default application service for product-card fetch."""

    cfg = settings or get_settings()
    proxy_pool = ProxyPool.from_csv(
        cfg.competitor_audit_proxy_urls or cfg.stock_parser_proxy_urls
    )
    timeout = cfg.stock_parser_timeout_seconds
    delay_min = cfg.stock_parser_request_delay_min_seconds
    delay_max = cfg.stock_parser_request_delay_max_seconds

    wb = WildberriesDeepClient(
        card_base_url=cfg.stock_parser_wb_card_base_url,
        dest=cfg.stock_parser_wb_dest,
        timeout_seconds=timeout,
        proxy_pool=proxy_pool,
        request_delay_min_seconds=delay_min,
        request_delay_max_seconds=delay_max,
    )
    ozon = OzonDeepClient(
        base_url=cfg.stock_parser_ozon_api_base_url,
        timeout_seconds=timeout,
        proxy_pool=proxy_pool,
        request_delay_min_seconds=delay_min,
        request_delay_max_seconds=delay_max,
    )
    return ProductCardParserService(
        scrapers={
            CompetitorMarketplace.WILDBERRIES: wb,
            CompetitorMarketplace.OZON: ozon,
        },
        image_downloader=CompetitorCardImageFetcher(timeout_seconds=timeout),
        object_storage=storage if storage is not None else _LazyS3Storage(),
        cache=RedisProductCardCache(),
        cache_ttl_seconds=REDIS_PRODUCT_CARD_TTL_SECONDS,
    )
