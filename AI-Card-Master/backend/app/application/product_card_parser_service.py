"""Use case: resolve WB/Ozon article or URL → structured card with S3 images."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.application.ports.product_card_parser import (
    ProductCardCachePort,
    ProductCardImageDownloaderPort,
    ProductCardObjectStoragePort,
    ProductCardScraperPort,
)
from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorProductLink,
)
from app.domain.product_card_parser import (
    PRODUCT_CARD_NOT_FOUND_ERROR,
    REDIS_PRODUCT_CARD_TTL_SECONDS,
    ProductCardCharacteristic,
    ProductCardFetchRequest,
    ProductCardFetchResult,
    ProductCardNotFoundError,
    ProductCardValidationError,
    redis_product_card_cache_key,
    resolve_product_card_input,
)
from app.domain.stock_parser import ParserErrorKind
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)
from app.services.s3_storage import S3StorageConfigurationError, S3StorageError

logger = logging.getLogger(__name__)

_MAX_GALLERY_IMAGES = 40
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class _NullProductCardCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(
        self, key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        return None


class ProductCardParserService:
    """Orchestrate resolve → Redis → deep scrape → S3 re-host → cache."""

    def __init__(
        self,
        *,
        scrapers: dict[CompetitorMarketplace, ProductCardScraperPort],
        image_downloader: ProductCardImageDownloaderPort,
        object_storage: ProductCardObjectStoragePort,
        cache: ProductCardCachePort | None = None,
        cache_ttl_seconds: int = REDIS_PRODUCT_CARD_TTL_SECONDS,
        max_gallery_images: int = _MAX_GALLERY_IMAGES,
    ) -> None:
        self._scrapers = scrapers
        self._images = image_downloader
        self._storage = object_storage
        self._cache = cache or _NullProductCardCache()
        self._cache_ttl = max(1, int(cache_ttl_seconds))
        self._max_gallery = max(1, int(max_gallery_images))

    async def fetch(
        self, request: ProductCardFetchRequest
    ) -> ProductCardFetchResult:
        link = resolve_product_card_input(request.input, request.platform)
        cache_key = redis_product_card_cache_key(
            marketplace=link.marketplace,
            article=link.article,
        )

        cached = await self._safe_cache_get(cache_key)
        if cached is not None:
            try:
                return ProductCardFetchResult.from_cache_payload(cached)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Invalid product-card cache payload for %s; refetching.",
                    cache_key,
                )

        scrape = await self._scrape(link)
        title = (scrape.title or "").strip()
        if not title:
            raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR)

        source_urls = list(scrape.photo_urls)
        s3_urls = await self._upload_gallery(
            marketplace=link.marketplace,
            article=link.article,
            source_urls=source_urls,
        )

        result = ProductCardFetchResult(
            marketplace=link.marketplace.value,  # type: ignore[arg-type]
            sku=link.article,
            product_url=link.url,
            title=title[:500],
            brand=(scrape.brand.strip()[:256] if scrape.brand else None),
            description=scrape.description or None,
            characteristics=[
                ProductCardCharacteristic(name=row.name, value=row.value)
                for row in scrape.specs
            ],
            image_urls=s3_urls,
            source_image_urls=source_urls,
            price_kopecks=scrape.price_after_discount_kopecks,
            price_before_discount_kopecks=scrape.price_before_discount_kopecks,
            currency=scrape.currency or "RUB",
            cached=False,
        )
        await self._safe_cache_set(cache_key, result.to_cache_payload())
        return result

    async def aclose(self) -> None:
        for scraper in self._scrapers.values():
            await scraper.aclose()
        await self._images.aclose()

    async def _scrape(self, link: CompetitorProductLink) -> CompetitorCardScrapeResult:
        scraper = self._scrapers.get(link.marketplace)
        if scraper is None:
            raise ProductCardValidationError(
                f"No scraper configured for marketplace '{link.marketplace.value}'."
            )
        try:
            return await scraper.scrape_card(link)
        except ParserHttpError as exc:
            if _is_not_found_or_blocked(exc):
                raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR) from exc
            logger.exception(
                "Marketplace HTTP error while scraping %s/%s",
                link.marketplace.value,
                link.article,
            )
            raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR) from exc
        except ParserSchemaError as exc:
            # Empty products[] / schema drift without title → treat as not found.
            raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR) from exc
        except ParserTransportError as exc:
            logger.warning(
                "Marketplace transport error for %s/%s: %s",
                link.marketplace.value,
                link.article,
                exc,
            )
            raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR) from exc
        except ProductCardNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected scrape failure for %s/%s",
                link.marketplace.value,
                link.article,
            )
            raise ProductCardNotFoundError(PRODUCT_CARD_NOT_FOUND_ERROR) from exc

    async def _upload_gallery(
        self,
        *,
        marketplace: CompetitorMarketplace,
        article: str,
        source_urls: list[str],
    ) -> list[str]:
        if not source_urls:
            return []

        downloaded = await self._images.fetch_urls(
            urls=source_urls,
            max_images=self._max_gallery,
        )
        uploaded: list[str] = []
        for index, (payload, mime, _source) in enumerate(downloaded, start=1):
            ext = _MIME_TO_EXT.get(mime.casefold(), "bin")
            object_key = (
                f"parser/{marketplace.value}/{article}/"
                f"{index:02d}_{uuid4().hex[:10]}.{ext}"
            )
            try:
                result = await self._storage.upload_bytes(
                    object_key=object_key,
                    data=payload,
                    content_type=mime or "application/octet-stream",
                    presign=True,
                    cache_control="public, max-age=3600",
                )
            except S3StorageConfigurationError:
                raise
            except S3StorageError as exc:
                logger.warning(
                    "S3 upload failed for %s/%s image #%s: %s",
                    marketplace.value,
                    article,
                    index,
                    exc,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected S3 upload failure for %s/%s image #%s: %s",
                    marketplace.value,
                    article,
                    index,
                    exc,
                )
                continue
            url = getattr(result, "presigned_url", None) or ""
            if not url:
                bucket = getattr(result, "bucket", "")
                key = getattr(result, "object_key", object_key)
                if bucket:
                    url = f"s3://{bucket}/{key}"
            if url:
                uploaded.append(str(url))
        return uploaded

    async def _safe_cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            return await self._cache.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Product-card cache read failed: %s", exc)
            return None

    async def _safe_cache_set(self, key: str, payload: dict[str, Any]) -> None:
        try:
            await self._cache.set(key, payload, self._cache_ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Product-card cache write failed: %s", exc)


def _is_not_found_or_blocked(exc: ParserHttpError) -> bool:
    if exc.status_code in {403, 404, 410, 429, 451}:
        return True
    return exc.kind in {
        ParserErrorKind.HTTP_403,
        ParserErrorKind.HTTP_404,
    }
