"""Ozon deep card scraper: gallery, description, specs, prices, reviews.

Uses composer-api page JSON consumed by Ozon mobile apps (no Selenium).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

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
from app.domain.stock_parser import ParserMarketplace
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)
from app.infrastructure.stock_parser.http_transport import MobileJsonTransport
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

DEFAULT_OZON_API_BASE = "https://api.ozon.ru"
_PRICE_RE = re.compile(r"[^\d.,]")


class OzonDeepClient:
    """Pull maximum raw Ozon card data for manual competitor audit."""

    marketplace = CompetitorMarketplace.OZON

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OZON_API_BASE,
        timeout_seconds: float = 20.0,
        proxy_pool: ProxyPool | None = None,
        transport: MobileJsonTransport | None = None,
        max_reviews: int = MAX_REVIEWS_PER_CARD,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_reviews = max(1, min(max_reviews, MAX_REVIEWS_PER_CARD))
        self._transport = transport or MobileJsonTransport(
            marketplace=ParserMarketplace.OZON,
            proxy_pool=proxy_pool,
            timeout_seconds=timeout_seconds,
        )

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        if link.marketplace is not CompetitorMarketplace.OZON:
            raise ParserSchemaError(
                "OzonDeepClient received non-Ozon link",
                marketplace=ParserMarketplace.OZON,
            )

        warnings: list[str] = []
        raw_fragments: dict[str, Any] = {}
        page_path = _composer_product_path(link.article, link.url)

        product_payload = await self._fetch_composer_page(page_path)
        raw_fragments["product_page"] = truncate_raw_fragment(product_payload)

        title = _find_first_str(product_payload, ("title", "name", "cellTrackingInfo"))
        description = _extract_description(product_payload)
        specs = _extract_specs(product_payload)
        brand = _extract_brand(product_payload, specs)
        photo_urls = _prefer_max_resolution_urls(_extract_photo_urls(product_payload))
        price_after, price_before = _extract_prices(product_payload)

        if not photo_urls:
            warnings.append("gallery photos not found in composer widgets.")
        if not description:
            warnings.append("full description missing in composer widgets.")
        if not specs:
            warnings.append("characteristics table missing in composer widgets.")

        reviews: list[CompetitorReview] = []
        try:
            reviews_payload = await self._fetch_composer_page(
                f"/product/{link.article}/reviews/"
            )
            raw_fragments["reviews_page"] = truncate_raw_fragment(reviews_payload)
            reviews = _extract_reviews(reviews_payload, limit=self._max_reviews)
        except (ParserTransportError, ParserHttpError, ParserSchemaError) as exc:
            warnings.append(f"reviews fetch degraded: {exc}")
            # Fallback: some product pages embed a review preview.
            reviews = _extract_reviews(product_payload, limit=self._max_reviews)

        if not reviews:
            warnings.append("no reviews extracted (marketplace may throttle).")

        low, high = split_reviews_by_rating(reviews)
        return CompetitorCardScrapeResult(
            source_url=link.url,
            marketplace=CompetitorMarketplace.OZON,
            article=link.article,
            title=title[:500] if title else None,
            brand=brand[:256] if brand else None,
            description=description[:50_000],
            specs=specs[:200],
            photo_urls=photo_urls[:100],
            price_before_discount_kopecks=price_before,
            price_after_discount_kopecks=price_after,
            currency="RUB",
            reviews_total_fetched=len(reviews),
            reviews_low=low,
            reviews_high=high,
            scrape_warnings=warnings,
            raw_fragments=raw_fragments,
        )

    async def _fetch_composer_page(self, page_path: str) -> dict[str, Any]:
        url = f"{self._base_url}/composer-api.bx/page/json/v2"
        params = {"url": page_path}
        return await self._transport.get_json(url, params=params)

    async def aclose(self) -> None:
        await self._transport.aclose()


def _composer_product_path(sku: str, product_url: str) -> str:
    path = urlparse(product_url).path or ""
    if path.startswith("/product/"):
        return path if path.endswith("/") else f"{path}/"
    return f"/product/{sku}/"


def _walk(obj: Any):
    """Depth-first walk of nested dict/list structures."""

    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _find_first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for node in _walk(payload):
        for key in keys:
            if key not in node:
                continue
            value = node[key]
            if isinstance(value, str) and value.strip() and key != "cellTrackingInfo":
                return value.strip()
            if isinstance(value, dict) and "title" in value:
                title = value.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()
    return None


def _extract_description(payload: dict[str, Any]) -> str:
    candidates: list[str] = []
    for node in _walk(payload):
        for key in ("description", "richAnnotation", "text", "html"):
            value = node.get(key)
            if isinstance(value, str):
                text = re.sub(r"<[^>]+>", " ", value)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) >= 40:
                    candidates.append(text)
        # Ozon description sections often nest under "sections".
        sections = node.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                title = str(section.get("title") or "").casefold()
                if "описан" in title or "description" in title:
                    body = section.get("text") or section.get("description")
                    if isinstance(body, str) and body.strip():
                        candidates.append(re.sub(r"\s+", " ", body.strip()))
    if not candidates:
        return ""
    return max(candidates, key=len)


def _extract_specs(payload: dict[str, Any]) -> list[CompetitorSpecRow]:
    specs: list[CompetitorSpecRow] = []
    seen: set[str] = set()
    for node in _walk(payload):
        # Common Ozon characteristic shapes.
        for key in ("characteristics", "shortCharacteristics", "attrs", "attributes"):
            rows = node.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(
                    row.get("name") or row.get("key") or row.get("title") or ""
                ).strip()
                values = row.get("values") or row.get("value") or row.get("text")
                if isinstance(values, list):
                    value = ", ".join(
                        str(v.get("text") if isinstance(v, dict) else v)
                        for v in values
                        if v is not None
                    ).strip()
                else:
                    value = str(values or "").strip()
                if not name or not value:
                    continue
                dedupe = name.casefold()
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                specs.append(CompetitorSpecRow(name=name[:256], value=value[:2000]))
        # Key/value pairs in aspect tables.
        if "key" in node and "value" in node:
            name = str(node.get("key") or "").strip()
            value = str(node.get("value") or "").strip()
            if name and value and name.casefold() not in seen:
                seen.add(name.casefold())
                specs.append(CompetitorSpecRow(name=name[:256], value=value[:2000]))
    return specs


def _extract_brand(
    payload: dict[str, Any],
    specs: list[CompetitorSpecRow],
) -> str | None:
    for node in _walk(payload):
        for key in ("brandName", "brand", "brandTitle", "trademark"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = value.get("name") or value.get("title") or value.get("text")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    for row in specs:
        if row.name.casefold() in {"бренд", "brand", "торговая марка", "марка"}:
            return row.value.strip() or None
    return None


def _prefer_max_resolution_urls(urls: list[str]) -> list[str]:
    """Deduplicate near-identical Ozon CDN variants; keep the largest size tip."""

    if not urls:
        return []
    scored: list[tuple[int, int, str]] = []
    for index, url in enumerate(urls):
        score = 0
        lowered = url.casefold()
        for token, weight in (
            ("wc2000", 2000),
            ("wc1200", 1200),
            ("wc1000", 1000),
            ("wc800", 800),
            ("wc750", 750),
            ("original", 3000),
            ("/video/", -5000),
        ):
            if token in lowered:
                score = max(score, weight)
        scored.append((score, -index, url))
    scored.sort(reverse=True)
    # Keep original discovery order among unique hosts/paths after size preference:
    # take highest-scoring unique basename group first, preserve relative order.
    ordered = [url for _, _, url in sorted(scored, key=lambda row: (-row[0], -row[1]))]
    return ordered


def _extract_photo_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for node in _walk(payload):
        for key in ("images", "gallery", "photos", "coverImageItems", "items"):
            items = node.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                candidates: list[str] = []
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    for img_key in (
                        "url",
                        "src",
                        "image",
                        "imageUrl",
                        "original",
                        "link",
                    ):
                        val = item.get(img_key)
                        if isinstance(val, str):
                            candidates.append(val)
                        elif isinstance(val, dict):
                            for nested in ("url", "src", "link"):
                                nested_val = val.get(nested)
                                if isinstance(nested_val, str):
                                    candidates.append(nested_val)
                for candidate in candidates:
                    url = candidate.strip()
                    if not url.startswith("http"):
                        continue
                    # Prefer full-size gallery assets.
                    if url in seen:
                        continue
                    if any(
                        token in url.casefold()
                        for token in ("avatar", "icon", "logo", "sprite")
                    ):
                        continue
                    seen.add(url)
                    urls.append(url)
        for key in ("image", "coverImage", "mainImage"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith("http") and value not in seen:
                seen.add(value)
                urls.append(value)
    return urls


def _extract_prices(
    payload: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Return (price_after_discount, price_before_discount) in kopecks."""

    after: int | None = None
    before: int | None = None
    for node in _walk(payload):
        # Prefer explicit card/price fields.
        for after_key, before_key in (
            ("cardPrice", "price"),
            ("price", "originalPrice"),
            ("finalPrice", "price"),
            ("salePrice", "price"),
        ):
            if after_key in node:
                candidate_after = _to_kopecks(node.get(after_key))
                candidate_before = _to_kopecks(node.get(before_key))
                if candidate_after and after is None:
                    after = candidate_after
                if candidate_before and before is None:
                    before = candidate_before
        if "price" in node and after is None:
            after = _to_kopecks(node.get("price"))
        if "originalPrice" in node and before is None:
            before = _to_kopecks(node.get("originalPrice"))
        if after is not None and before is not None:
            break
    if after is not None and before is not None and before < after:
        before, after = after, before
    return after, before


def _to_kopecks(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100 if value < 1_000_000 else value
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, str):
        digits = _PRICE_RE.sub("", value).replace(",", ".")
        if not digits:
            return None
        try:
            return int(round(float(digits) * 100))
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in (
            "cardPrice",
            "price",
            "totalPrice",
            "value",
            "originalPrice",
            "text",
        ):
            if key in value:
                converted = _to_kopecks(value[key])
                if converted is not None:
                    return converted
    return None


def _extract_reviews(
    payload: dict[str, Any], *, limit: int
) -> list[CompetitorReview]:
    reviews: list[CompetitorReview] = []
    seen_ids: set[str] = set()
    for node in _walk(payload):
        # Direct review objects.
        rating = (
            node.get("rating")
            or node.get("score")
            or node.get("productScore")
            or node.get("contentRating")
        )
        text = node.get("text") or node.get("comment") or node.get("content")
        if rating is None or not isinstance(text, (str, type(None))):
            # Also accept reviews nested under reviews/items lists handled by walk.
            pass
        try:
            rating_int = int(rating) if rating is not None else 0
        except (TypeError, ValueError):
            rating_int = 0
        if 1 <= rating_int <= 5 and isinstance(text, str):
            review_id = node.get("uuid") or node.get("id") or node.get("reviewId")
            rid = str(review_id) if review_id is not None else None
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            author = None
            author_node = node.get("author") or node.get("user") or {}
            if isinstance(author_node, dict):
                author = str(
                    author_node.get("firstName")
                    or author_node.get("name")
                    or author_node.get("displayName")
                    or ""
                ) or None
            elif isinstance(author_node, str):
                author = author_node
            created = node.get("publishedAt") or node.get("createdAt")
            reviews.append(
                CompetitorReview(
                    review_id=rid[:128] if rid else None,
                    rating=rating_int,
                    text=text.strip()[:8000],
                    author=author[:256] if author else None,
                    created_at=str(created)[:64] if created is not None else None,
                    pros=str(node.get("pros") or "")[:4000] or None,
                    cons=str(node.get("cons") or "")[:4000] or None,
                )
            )
            if len(reviews) >= limit:
                return reviews
    return reviews[:limit]
