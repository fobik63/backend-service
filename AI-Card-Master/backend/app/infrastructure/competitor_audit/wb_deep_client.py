"""Wildberries deep card scraper: gallery, description, specs, prices, reviews.

Uses public mobile/content JSON endpoints (no Selenium / no HTML).
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.competitor_audit import (
    MAX_REVIEWS_PER_CARD,
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorProductLink,
    CompetitorReview,
    CompetitorSpecRow,
    split_reviews_by_rating,
    truncate_raw_fragment,
)
from app.domain.eye_of_god import wildberries_primary_image_urls
from app.domain.stock_parser import ParserMarketplace
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)
from app.infrastructure.stock_parser.http_transport import MobileJsonTransport
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

DEFAULT_WB_CARD_BASE = "https://card.wb.ru"
DEFAULT_WB_CONTENT_BASE = "https://wbx-content-v2.wbstatic.net"
_FEEDBACK_HOSTS = (
    "https://feedbacks1.wb.ru",
    "https://feedbacks2.wb.ru",
)


class WildberriesDeepClient:
    """Pull maximum raw WB card data for manual competitor audit."""

    marketplace = CompetitorMarketplace.WILDBERRIES

    def __init__(
        self,
        *,
        card_base_url: str = DEFAULT_WB_CARD_BASE,
        content_base_url: str = DEFAULT_WB_CONTENT_BASE,
        dest: int = -1257786,
        timeout_seconds: float = 20.0,
        proxy_pool: ProxyPool | None = None,
        transport: MobileJsonTransport | None = None,
        max_reviews: int = MAX_REVIEWS_PER_CARD,
    ) -> None:
        self._card_base_url = card_base_url.rstrip("/")
        self._content_base_url = content_base_url.rstrip("/")
        self._dest = dest
        self._max_reviews = max(1, min(max_reviews, MAX_REVIEWS_PER_CARD))
        self._transport = transport or MobileJsonTransport(
            marketplace=ParserMarketplace.WILDBERRIES,
            proxy_pool=proxy_pool,
            timeout_seconds=timeout_seconds,
        )

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        if link.marketplace is not CompetitorMarketplace.WILDBERRIES:
            raise ParserSchemaError(
                "WildberriesDeepClient received non-WB link",
                marketplace=ParserMarketplace.WILDBERRIES,
            )

        nm_id = int(link.article)
        warnings: list[str] = []
        raw_fragments: dict[str, Any] = {}

        card_payload = await self._fetch_card_detail(nm_id)
        product = _extract_wb_product(card_payload)
        raw_fragments["card_detail"] = truncate_raw_fragment(card_payload)

        title = str(product.get("name") or "").strip() or None
        brand = _extract_wb_brand(product)
        sale = int(product.get("salePriceU") or 0)
        price = int(product.get("priceU") or sale)
        pics_count = int(product.get("pics") or 0)
        root_id = product.get("root") or product.get("imt_id") or product.get("imtId")

        photo_urls = list(
            wildberries_primary_image_urls(nm_id, count=max(pics_count, 1))
        )
        if pics_count <= 0:
            warnings.append("pics count missing; defaulted to first gallery image.")

        description = ""
        specs: list[CompetitorSpecRow] = []
        try:
            content_payload = await self._fetch_content(nm_id)
            raw_fragments["content"] = truncate_raw_fragment(content_payload)
            description, specs = _map_wb_content(content_payload)
            if brand is None:
                brand = _extract_wb_brand(content_payload)
        except (ParserTransportError, ParserHttpError, ParserSchemaError) as exc:
            warnings.append(f"content fetch degraded: {exc}")
            # Fallback: description sometimes present on card product.
            description = str(product.get("description") or "").strip()

        reviews: list[CompetitorReview] = []
        if root_id is not None:
            try:
                feedback_payload = await self._fetch_feedbacks(int(root_id), nm_id)
                raw_fragments["feedbacks"] = truncate_raw_fragment(feedback_payload)
                reviews = _map_wb_feedbacks(feedback_payload, limit=self._max_reviews)
            except (ParserTransportError, ParserHttpError, ParserSchemaError) as exc:
                warnings.append(f"feedbacks fetch degraded: {exc}")
        else:
            warnings.append("root/imt id missing; skipped reviews.")

        low, high = split_reviews_by_rating(reviews)
        return CompetitorCardScrapeResult(
            source_url=link.url,
            marketplace=CompetitorMarketplace.WILDBERRIES,
            article=link.article,
            title=title[:500] if title else None,
            brand=brand[:256] if brand else None,
            description=description[:50_000],
            specs=specs[:200],
            photo_urls=photo_urls[:100],
            price_before_discount_kopecks=price if price > 0 else None,
            price_after_discount_kopecks=sale if sale > 0 else None,
            currency="RUB",
            reviews_total_fetched=len(reviews),
            reviews_low=low,
            reviews_high=high,
            scrape_warnings=warnings,
            raw_fragments=raw_fragments,
        )

    async def _fetch_card_detail(self, nm_id: int) -> dict[str, Any]:
        url = f"{self._card_base_url}/cards/v1/detail"
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": self._dest,
            "nm": nm_id,
        }
        return await self._transport.get_json(url, params=params)

    async def _fetch_content(self, nm_id: int) -> dict[str, Any]:
        url = f"{self._content_base_url}/ru/{nm_id}.json"
        return await self._transport.get_json(url)

    async def _fetch_feedbacks(self, root_id: int, nm_id: int) -> dict[str, Any]:
        last_error: Exception | None = None
        # Prefer root-based v1; fall back to nm-based v2 hosts.
        candidates = [
            (f"{host}/feedbacks/v1/{root_id}", None) for host in _FEEDBACK_HOSTS
        ] + [
            (f"{host}/feedbacks/v2/{nm_id}", None) for host in _FEEDBACK_HOSTS
        ]
        for url, params in candidates:
            try:
                return await self._transport.get_json(url, params=params)
            except (ParserTransportError, ParserHttpError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise ParserTransportError(
            f"Unable to fetch WB feedbacks for nm={nm_id}",
            marketplace=ParserMarketplace.WILDBERRIES,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()


def _extract_wb_product(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        products = data.get("products")
        if isinstance(products, list) and products:
            first = products[0]
            if isinstance(first, dict):
                return first
        if isinstance(products, list) and not products:
            raise ParserSchemaError(
                "Wildberries card payload has empty products list",
                marketplace=ParserMarketplace.WILDBERRIES,
                missing_keys=("products",),
            )
    products = payload.get("products")
    if isinstance(products, list) and products and isinstance(products[0], dict):
        return products[0]
    if isinstance(products, list) and not products:
        raise ParserSchemaError(
            "Wildberries card payload has empty products list",
            marketplace=ParserMarketplace.WILDBERRIES,
            missing_keys=("products",),
        )
    if "name" in payload or "salePriceU" in payload:
        return payload
    raise ParserSchemaError(
        "Wildberries card payload missing products[0]",
        marketplace=ParserMarketplace.WILDBERRIES,
        missing_keys=("products",),
    )


def _extract_wb_brand(payload: dict[str, Any]) -> str | None:
    for key in ("brand", "brandName", "sellingBrand", "trademark"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("name") or value.get("title")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    selling = payload.get("selling")
    if isinstance(selling, dict):
        brand = selling.get("brandName") or selling.get("brand")
        if isinstance(brand, str) and brand.strip():
            return brand.strip()
    return None


def _map_wb_content(
    payload: dict[str, Any],
) -> tuple[str, list[CompetitorSpecRow]]:
    description = str(
        payload.get("description")
        or payload.get("imt_description")
        or payload.get("full_description")
        or ""
    ).strip()

    specs: list[CompetitorSpecRow] = []
    options = payload.get("options") or payload.get("characteristics") or []
    if isinstance(options, list):
        for item in options:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("key") or "").strip()
            value = item.get("value") or item.get("values") or item.get("val")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v is not None)
            value_str = str(value or "").strip()
            if name and value_str:
                specs.append(CompetitorSpecRow(name=name[:256], value=value_str[:2000]))

    grouped = payload.get("grouped_options")
    if isinstance(grouped, list):
        for group in grouped:
            if not isinstance(group, dict):
                continue
            for item in group.get("options") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                value = str(item.get("value") or "").strip()
                if name and value:
                    specs.append(
                        CompetitorSpecRow(name=name[:256], value=value[:2000])
                    )

    # Deduplicate by name while preserving order.
    seen: set[str] = set()
    unique: list[CompetitorSpecRow] = []
    for row in specs:
        key = row.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return description, unique


def _map_wb_feedbacks(
    payload: dict[str, Any], *, limit: int
) -> list[CompetitorReview]:
    items = payload.get("feedbacks") or payload.get("data") or []
    if isinstance(items, dict):
        items = items.get("feedbacks") or []
    if not isinstance(items, list):
        return []

    reviews: list[CompetitorReview] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rating_raw = (
            item.get("productValuation")
            or item.get("product_valuation")
            or item.get("valuation")
            or item.get("rating")
            or 0
        )
        try:
            rating = int(rating_raw)
        except (TypeError, ValueError):
            continue
        if rating < 1 or rating > 5:
            continue
        text = str(item.get("text") or item.get("comment") or "").strip()
        pros = item.get("pros") or item.get("advantages")
        cons = item.get("cons") or item.get("disadvantages")
        author = None
        wb_user = item.get("wbUserDetails") or item.get("userDetails") or {}
        if isinstance(wb_user, dict):
            author = str(wb_user.get("name") or wb_user.get("displayName") or "") or None
        created = item.get("createdDate") or item.get("created") or item.get("date")
        review_id = item.get("id") or item.get("feedbackId")
        reviews.append(
            CompetitorReview(
                review_id=str(review_id)[:128] if review_id is not None else None,
                rating=rating,
                text=text[:8000],
                author=author[:256] if author else None,
                created_at=str(created)[:64] if created is not None else None,
                pros=str(pros)[:4000] if pros else None,
                cons=str(cons)[:4000] if cons else None,
            )
        )
        if len(reviews) >= limit:
            break
    return reviews
