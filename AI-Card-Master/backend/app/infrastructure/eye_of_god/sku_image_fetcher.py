"""Download current marketplace card photos for Eye-of-God Vision."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.domain.bulk_generation import detect_image_mime
from app.domain.eye_of_god import wildberries_primary_image_urls
from app.domain.stock_parser import ParserMarketplace

logger = logging.getLogger(__name__)


class SkuCardImageFetcher:
    """httpx-only card image fetch (no Selenium) for Claude Vision."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 8_000_000,
        user_agent: str = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        ),
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )

    async def fetch_current_images(
        self,
        *,
        marketplace: str,
        article: str,
        product_url: str | None = None,
        preferred_urls: tuple[str, ...] = (),
        max_images: int = 3,
    ) -> tuple[tuple[bytes, str, str], ...]:
        """Return ((bytes, mime_type, source_url), ...) up to ``max_images``."""

        candidates = list(preferred_urls)
        if not candidates:
            candidates.extend(
                self._resolve_fallback_urls(
                    marketplace=marketplace,
                    article=article,
                    product_url=product_url,
                    count=max_images,
                )
            )

        results: list[tuple[bytes, str, str]] = []
        seen: set[str] = set()
        for url in candidates:
            cleaned = (url or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            fetched = await self._download_one(cleaned)
            if fetched is None:
                continue
            results.append(fetched)
            if len(results) >= max(1, max_images):
                break
        return tuple(results)

    def _resolve_fallback_urls(
        self,
        *,
        marketplace: str,
        article: str,
        product_url: str | None,
        count: int,
    ) -> list[str]:
        market = marketplace.strip().lower()
        if market == ParserMarketplace.WILDBERRIES.value:
            digits = "".join(ch for ch in article if ch.isdigit())
            if not digits and product_url:
                path = urlparse(product_url).path
                for part in reversed(path.rstrip("/").split("/")):
                    if part.isdigit():
                        digits = part
                        break
            if digits:
                return list(
                    wildberries_primary_image_urls(int(digits), count=count)
                )
        # Ozon: prefer preferred_urls / raw payload; no stable public CDN formula.
        return []

    async def _download_one(self, url: str) -> tuple[bytes, str, str] | None:
        try:
            response = await self._client.get(url)
            if response.status_code >= 400:
                logger.warning(
                    "Eye-of-God image fetch HTTP %s for %s",
                    response.status_code,
                    url[:120],
                )
                return None
            payload = response.content
            if not payload or len(payload) > self._max_bytes:
                return None
            content_type = (response.headers.get("content-type") or "").split(";")[
                0
            ].strip()
            mime = content_type if content_type.startswith("image/") else ""
            if not mime:
                detected = detect_image_mime(payload)
                mime = detected[0] if detected else "image/jpeg"
            return payload, mime, url
        except httpx.HTTPError as exc:
            logger.warning("Eye-of-God image fetch failed for %s: %s", url[:120], exc)
            return None

    @staticmethod
    def extract_image_urls_from_raw_payload(
        marketplace: str,
        raw_payload: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        """Best-effort extraction of photo URLs from mobile JSON payloads."""

        if not raw_payload:
            return ()
        market = marketplace.strip().lower()
        found: list[str] = []

        def _walk(node: Any, *, depth: int = 0) -> None:
            if depth > 6 or len(found) >= 10:
                return
            if isinstance(node, str):
                lower = node.lower()
                if lower.startswith("http") and any(
                    token in lower
                    for token in (".webp", ".jpg", ".jpeg", ".png", "/images/")
                ):
                    found.append(node)
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    key_l = str(key).lower()
                    if key_l in {
                        "photos",
                        "images",
                        "gallery",
                        "pics",
                        "media",
                        "picture",
                        "url",
                        "src",
                    }:
                        _walk(value, depth=depth + 1)
                    elif isinstance(value, (dict, list)):
                        _walk(value, depth=depth + 1)
                return
            if isinstance(node, list):
                for item in node[:20]:
                    _walk(item, depth=depth + 1)

        if market == ParserMarketplace.WILDBERRIES.value:
            products = raw_payload.get("data", {}).get("products")
            if isinstance(products, list) and products:
                _walk(products[0])
            else:
                _walk(raw_payload)
        else:
            _walk(raw_payload)

        # Deduplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for url in found:
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
        return tuple(out[:10])

    async def aclose(self) -> None:
        await self._client.aclose()
