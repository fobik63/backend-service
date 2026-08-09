"""Discover TOP-N similar Wildberries products for Eye of God spy."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.competitor_audit import CompetitorMarketplace
from app.domain.eye_of_god_spy import CompetitorDiscoveryHit
from app.domain.stock_parser import ParserMarketplace
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)
from app.infrastructure.stock_parser.http_transport import MobileJsonTransport
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

DEFAULT_WB_SEARCH_BASE = "https://search.wb.ru"
_WB_PRODUCT_URL = "https://www.wildberries.ru/catalog/{article}/detail.aspx"
_QUERY_CLEAN_RE = re.compile(r"\s+")


class WildberriesCompetitorDiscovery:
    """Search WB catalog by query and return ranked competitor hits."""

    marketplace = CompetitorMarketplace.WILDBERRIES

    def __init__(
        self,
        *,
        search_base_url: str = DEFAULT_WB_SEARCH_BASE,
        dest: int = -1257786,
        timeout_seconds: float = 20.0,
        proxy_pool: ProxyPool | None = None,
        transport: MobileJsonTransport | None = None,
        request_delay_min_seconds: float | None = None,
        request_delay_max_seconds: float | None = None,
    ) -> None:
        self._search_base_url = search_base_url.rstrip("/")
        self._dest = dest
        transport_kwargs: dict[str, float] = {}
        if request_delay_min_seconds is not None:
            transport_kwargs["request_delay_min_seconds"] = request_delay_min_seconds
        if request_delay_max_seconds is not None:
            transport_kwargs["request_delay_max_seconds"] = request_delay_max_seconds
        self._transport = transport or MobileJsonTransport(
            marketplace=ParserMarketplace.WILDBERRIES,
            proxy_pool=proxy_pool,
            timeout_seconds=timeout_seconds,
            **transport_kwargs,
        )

    async def discover_by_query(
        self,
        *,
        query: str,
        exclude_article: str | None = None,
        limit: int = 10,
    ) -> list[CompetitorDiscoveryHit]:
        cleaned = _QUERY_CLEAN_RE.sub(" ", (query or "").strip())
        if len(cleaned) < 2:
            raise ParserSchemaError(
                "Search query too short for competitor discovery",
                marketplace=ParserMarketplace.WILDBERRIES,
            )

        payload = await self._fetch_search(cleaned)
        products = _extract_products(payload)
        exclude = (exclude_article or "").strip()
        hits: list[CompetitorDiscoveryHit] = []
        seen: set[str] = set()

        for product in products:
            if not isinstance(product, dict):
                continue
            article = str(product.get("id") or product.get("nmId") or "").strip()
            if not article or not article.isdigit():
                continue
            if article == exclude or article in seen:
                continue
            seen.add(article)
            title = str(product.get("name") or "").strip() or None
            brand = str(product.get("brand") or product.get("brandName") or "").strip() or None
            sale = int(product.get("salePriceU") or product.get("priceU") or 0)
            price_rub = round(sale / 100.0, 2) if sale > 0 else None
            rating_raw = product.get("reviewRating") or product.get("rating")
            try:
                rating = float(rating_raw) if rating_raw is not None else None
            except (TypeError, ValueError):
                rating = None
            feedbacks_raw = product.get("feedbacks") or product.get("nmFeedbacks")
            try:
                feedbacks = int(feedbacks_raw) if feedbacks_raw is not None else None
            except (TypeError, ValueError):
                feedbacks = None

            hits.append(
                CompetitorDiscoveryHit(
                    rank=len(hits) + 1,
                    article=article,
                    url=_WB_PRODUCT_URL.format(article=article),
                    marketplace=CompetitorMarketplace.WILDBERRIES,
                    title=title[:500] if title else None,
                    brand=brand[:256] if brand else None,
                    price_rub=price_rub,
                    rating=rating if rating is not None and 0 <= rating <= 5 else None,
                    feedbacks=feedbacks if feedbacks is not None and feedbacks >= 0 else None,
                )
            )
            if len(hits) >= limit:
                break

        if not hits:
            raise ParserSchemaError(
                "No competitor products found for query",
                marketplace=ParserMarketplace.WILDBERRIES,
                missing_keys=("products",),
            )
        return hits

    async def _fetch_search(self, query: str) -> dict[str, Any]:
        url = f"{self._search_base_url}/exactmatch/ru/common/v7/search"
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": self._dest,
            "query": query,
            "resultset": "catalog",
            "sort": "popular",
            "spp": 30,
            "suppressSpellcheck": 0,
        }
        try:
            return await self._transport.get_json(url, params=params)
        except (ParserTransportError, ParserHttpError) as primary_exc:
            # Fallback older paths used by some WB clients.
            last_exc: Exception = primary_exc
            for version in ("v5", "v4"):
                fallback = (
                    f"{self._search_base_url}/exactmatch/ru/common/{version}/search"
                )
                try:
                    return await self._transport.get_json(fallback, params=params)
                except (ParserTransportError, ParserHttpError) as exc:
                    last_exc = exc
            raise last_exc from primary_exc

    async def aclose(self) -> None:
        await self._transport.aclose()


def _extract_products(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        products = data.get("products")
        if isinstance(products, list):
            return products
    products = payload.get("products")
    if isinstance(products, list):
        return products
    return []
