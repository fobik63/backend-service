"""Unit tests for product-card fetch (resolve → scrape → S3 → Redis)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.parser import parser_alias_router, router as parser_router
from app.application.product_card_parser_service import ProductCardParserService
from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorProductLink,
    CompetitorSpecRow,
)
from app.domain.product_card_parser import (
    PRODUCT_CARD_NOT_FOUND_ERROR,
    ProductCardFetchRequest,
    ProductCardNotFoundError,
    ProductCardPlatform,
    ProductCardValidationError,
    redis_product_card_cache_key,
    resolve_product_card_input,
)
from app.domain.stock_parser import ParserErrorKind, ParserMarketplace
from app.infrastructure.stock_parser.exceptions import ParserHttpError, ParserSchemaError
from app.models.user import User


def test_resolve_wb_url_auto() -> None:
    link = resolve_product_card_input(
        "https://www.wildberries.ru/catalog/12345678/detail.aspx",
        ProductCardPlatform.AUTO,
    )
    assert link.marketplace is CompetitorMarketplace.WILDBERRIES
    assert link.article == "12345678"


def test_resolve_ozon_url_auto() -> None:
    link = resolve_product_card_input(
        "https://www.ozon.ru/product/some-slug-987654321/",
        ProductCardPlatform.AUTO,
    )
    assert link.marketplace is CompetitorMarketplace.OZON
    assert link.article == "987654321"


def test_resolve_bare_article_requires_platform() -> None:
    with pytest.raises(ProductCardValidationError):
        resolve_product_card_input("12345678", ProductCardPlatform.AUTO)


def test_resolve_bare_wb_article() -> None:
    link = resolve_product_card_input("12345678", ProductCardPlatform.WB)
    assert link.marketplace is CompetitorMarketplace.WILDBERRIES
    assert link.article == "12345678"
    assert "/catalog/12345678/" in link.url


def test_resolve_platform_mismatch() -> None:
    with pytest.raises(ProductCardValidationError):
        resolve_product_card_input(
            "https://www.ozon.ru/product/987654321/",
            ProductCardPlatform.WB,
        )


def test_redis_cache_key_stable() -> None:
    key_a = redis_product_card_cache_key(
        marketplace=CompetitorMarketplace.WILDBERRIES,
        article="12345678",
    )
    key_b = redis_product_card_cache_key(
        marketplace="wildberries",
        article="12345678",
    )
    assert key_a == key_b
    assert key_a.startswith("parser:product_card:wildberries:12345678:")


class _FakeScraper:
    def __init__(self, result: CompetitorCardScrapeResult | Exception) -> None:
        self._result = result
        self.closed = False

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        del link
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def aclose(self) -> None:
        self.closed = True


class _FakeImages:
    def __init__(self, payloads: tuple[tuple[bytes, str, str], ...] = ()) -> None:
        self._payloads = payloads
        self.closed = False

    async def fetch_urls(
        self, *, urls: list[str], max_images: int = 40
    ) -> tuple[tuple[bytes, str, str], ...]:
        del urls, max_images
        return self._payloads

    async def aclose(self) -> None:
        self.closed = True


class _FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> Any:
        del data, content_type, presign, cache_control
        self.uploads.append(object_key)

        class _Result:
            bucket = "test-bucket"
            object_key = ""
            etag = "etag"
            presigned_url = ""

        result = _Result()
        result.object_key = object_key
        result.presigned_url = f"https://cdn.example/{object_key}"
        return result


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.store.get(key)

    async def set(
        self, key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        assert ttl_seconds == 3600
        self.store[key] = dict(payload)


def _sample_card(
    *,
    marketplace: CompetitorMarketplace = CompetitorMarketplace.WILDBERRIES,
    title: str | None = "Test Product",
    brand: str | None = "TestBrand",
) -> CompetitorCardScrapeResult:
    return CompetitorCardScrapeResult(
        source_url="https://www.wildberries.ru/catalog/12345678/detail.aspx",
        marketplace=marketplace,
        article="12345678",
        title=title,
        brand=brand,
        description="Full description",
        specs=[CompetitorSpecRow(name="Цвет", value="чёрный")],
        photo_urls=["https://cdn.wb/img1.webp", "https://cdn.wb/img2.webp"],
        price_before_discount_kopecks=200_00,
        price_after_discount_kopecks=150_00,
        currency="RUB",
    )


@pytest.mark.asyncio
async def test_service_fetch_uploads_and_caches() -> None:
    cache = _FakeCache()
    storage = _FakeStorage()
    service = ProductCardParserService(
        scrapers={
            CompetitorMarketplace.WILDBERRIES: _FakeScraper(_sample_card()),
        },
        image_downloader=_FakeImages(
            (
                (b"img1", "image/webp", "https://cdn.wb/img1.webp"),
                (b"img2", "image/webp", "https://cdn.wb/img2.webp"),
            )
        ),
        object_storage=storage,
        cache=cache,
        cache_ttl_seconds=3600,
    )

    result = await service.fetch(
        ProductCardFetchRequest(input="12345678", platform=ProductCardPlatform.WB)
    )
    assert result.title == "Test Product"
    assert result.brand == "TestBrand"
    assert result.cached is False
    assert len(result.image_urls) == 2
    assert result.image_urls[0].startswith("https://cdn.example/parser/wildberries/")
    assert result.characteristics[0].name == "Цвет"
    assert len(cache.store) == 1

    cached = await service.fetch(
        ProductCardFetchRequest(input="12345678", platform=ProductCardPlatform.WB)
    )
    assert cached.cached is True
    assert cached.image_urls == result.image_urls


@pytest.mark.asyncio
async def test_service_maps_http_403_to_not_found() -> None:
    service = ProductCardParserService(
        scrapers={
            CompetitorMarketplace.WILDBERRIES: _FakeScraper(
                ParserHttpError(
                    "blocked",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    status_code=403,
                    kind=ParserErrorKind.HTTP_403,
                )
            ),
        },
        image_downloader=_FakeImages(),
        object_storage=_FakeStorage(),
        cache=_FakeCache(),
    )
    with pytest.raises(ProductCardNotFoundError) as exc_info:
        await service.fetch(
            ProductCardFetchRequest(input="12345678", platform=ProductCardPlatform.WB)
        )
    assert str(exc_info.value) == PRODUCT_CARD_NOT_FOUND_ERROR


@pytest.mark.asyncio
async def test_service_maps_empty_products_to_not_found() -> None:
    service = ProductCardParserService(
        scrapers={
            CompetitorMarketplace.WILDBERRIES: _FakeScraper(
                ParserSchemaError(
                    "empty",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    missing_keys=("products",),
                )
            ),
        },
        image_downloader=_FakeImages(),
        object_storage=_FakeStorage(),
        cache=_FakeCache(),
    )
    with pytest.raises(ProductCardNotFoundError):
        await service.fetch(
            ProductCardFetchRequest(input="12345678", platform=ProductCardPlatform.WB)
        )


@pytest.mark.asyncio
async def test_api_fetch_alias_returns_flat_not_found_error() -> None:
    app = FastAPI()
    app.include_router(parser_alias_router)

    async def _fake_user() -> User:
        return AsyncMock(spec=User)  # type: ignore[return-value]

    class _BoomService:
        async def fetch(self, request: ProductCardFetchRequest) -> Any:
            del request
            raise ProductCardNotFoundError()

        async def aclose(self) -> None:
            return None

    from app.api import parser as parser_api
    from app.api.dependencies.auth import get_current_user

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[parser_api._get_product_card_parser_service] = (
        lambda: _BoomService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/parser/fetch",
            json={"input": "12345678", "platform": "wb"},
        )

    assert response.status_code == 404
    assert response.json() == {"error": PRODUCT_CARD_NOT_FOUND_ERROR}


def test_api_v1_and_alias_routes_registered() -> None:
    app = FastAPI()
    app.include_router(parser_router)
    app.include_router(parser_alias_router)
    paths = app.openapi()["paths"]
    assert "post" in (paths.get("/api/v1/parser/fetch") or {})
    assert "post" in (paths.get("/api/parser/fetch") or {})
    assert "post" in (paths.get("/api/v1/parser/parse") or {})
