"""REST API: Ozon / Wildberries product page parse + fetch (S3-backed).

- ``POST /api/v1/parser/parse`` — legacy editor payload (CDN image URLs).
- ``POST /api/parser/fetch`` (+ ``/api/v1/parser/fetch``) — article/URL →
  structured card with images re-hosted in internal S3 and Redis cache (1h).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import get_current_user
from app.application.product_card_parser_service import ProductCardParserService
from app.core.config import get_settings
from app.domain.competitor_audit import (
    CompetitorMarketplace,
    parse_competitor_product_link,
)
from app.domain.product_card_parser import (
    PRODUCT_CARD_NOT_FOUND_ERROR,
    ProductCardFetchRequest,
    ProductCardFetchResult,
    ProductCardNotFoundError,
    ProductCardPlatform,
    ProductCardValidationError,
)
from app.domain.stock_parser import ParserMarketplace, ParseSkuRequest
from app.infrastructure.competitor_audit.ozon_deep_client import OzonDeepClient
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient
from app.infrastructure.product_card_parser_factory import (
    build_product_card_parser_service,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserSchemaError,
    ParserTransportError,
)
from app.infrastructure.stock_parser.ozon_mobile_client import OzonMobileClient
from app.infrastructure.stock_parser.proxy_pool import ProxyPool
from app.infrastructure.stock_parser.wildberries_mobile_client import (
    WildberriesMobileClient,
)
from app.models.user import User
from app.services.s3_storage import S3StorageConfigurationError, S3StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/parser", tags=["parser"])
parser_alias_router = APIRouter(prefix="/api/parser", tags=["parser"])

MarketplaceId = Literal["wildberries", "ozon"]


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ParseProductRequest(StrictAPIModel):
    url: str = Field(..., min_length=12, max_length=2048)


class ParsedCharacteristicDTO(StrictAPIModel):
    name: str = Field(..., min_length=1, max_length=256)
    value: str = Field(..., min_length=1, max_length=2000)


class ParsedProductResponse(StrictAPIModel):
    marketplace: MarketplaceId
    sku: str = Field(..., min_length=1, max_length=64)
    product_url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(..., min_length=1, max_length=500)
    price_kopecks: int | None = Field(default=None, ge=0)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    description: str | None = None
    characteristics: list[ParsedCharacteristicDTO] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    total_stock: int | None = Field(default=None, ge=0)


class FetchProductRequest(StrictAPIModel):
    input: str = Field(..., min_length=1, max_length=2048)
    platform: Literal["auto", "wb", "ozon"] = "auto"


class FetchProductCharacteristicDTO(StrictAPIModel):
    name: str = Field(..., min_length=1, max_length=256)
    value: str = Field(..., min_length=1, max_length=2000)


class FetchProductResponse(StrictAPIModel):
    marketplace: MarketplaceId
    sku: str = Field(..., min_length=1, max_length=64)
    product_url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(..., min_length=1, max_length=500)
    brand: str | None = Field(default=None, max_length=256)
    description: str | None = None
    characteristics: list[FetchProductCharacteristicDTO] = Field(default_factory=list)
    image_urls: list[str] = Field(
        default_factory=list,
        description="Internal S3 presigned URLs for re-hosted gallery images.",
    )
    source_image_urls: list[str] = Field(
        default_factory=list,
        description="Original marketplace CDN URLs (max resolution).",
    )
    price_kopecks: int | None = Field(default=None, ge=0)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    cached: bool = False


def _to_parser_marketplace(mp: CompetitorMarketplace) -> ParserMarketplace:
    if mp is CompetitorMarketplace.WILDBERRIES:
        return ParserMarketplace.WILDBERRIES
    return ParserMarketplace.OZON


def _product_not_found_response() -> JSONResponse:
    """Flat client contract: ``{ \"error\": \"Товар не найден или заблокирован\" }``."""

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": PRODUCT_CARD_NOT_FOUND_ERROR},
    )


def _get_product_card_parser_service() -> ProductCardParserService:
    return build_product_card_parser_service()


def _to_fetch_response(result: ProductCardFetchResult) -> FetchProductResponse:
    return FetchProductResponse(
        marketplace=result.marketplace,
        sku=result.sku,
        product_url=result.product_url,
        title=result.title,
        brand=result.brand,
        description=result.description,
        characteristics=[
            FetchProductCharacteristicDTO(name=row.name, value=row.value)
            for row in result.characteristics
        ],
        image_urls=list(result.image_urls),
        source_image_urls=list(result.source_image_urls),
        price_kopecks=result.price_kopecks,
        price_before_discount_kopecks=result.price_before_discount_kopecks,
        currency=result.currency,
        cached=result.cached,
    )


async def _fetch_product_card(
    body: FetchProductRequest,
    service: ProductCardParserService,
) -> FetchProductResponse | JSONResponse:
    try:
        try:
            result = await service.fetch(
                ProductCardFetchRequest(
                    input=body.input,
                    platform=ProductCardPlatform(body.platform),
                )
            )
        except ProductCardValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except ProductCardNotFoundError:
            return _product_not_found_response()
        except S3StorageConfigurationError as exc:
            logger.exception("S3 is not configured for product-card fetch")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Object storage is not configured: {exc}",
            ) from exc
        except S3StorageError as exc:
            logger.exception("S3 failure during product-card fetch")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Object storage upload failed: {exc}",
            ) from exc
        return _to_fetch_response(result)
    finally:
        await service.aclose()


@router.post(
    "/parse",
    response_model=ParsedProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse Ozon / Wildberries product URL",
    description=(
        "Fetches mobile JSON stock snapshot + deep card scrape (title, specs, "
        "gallery) for a public WB/Ozon product page."
    ),
)
async def parse_product(
    body: ParseProductRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ParsedProductResponse:
    del current_user  # auth gate only

    try:
        link = parse_competitor_product_link(body.url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    proxy_pool = ProxyPool.from_csv(
        settings.competitor_audit_proxy_urls or settings.stock_parser_proxy_urls
    )
    timeout = settings.stock_parser_timeout_seconds
    parser_mp = _to_parser_marketplace(link.marketplace)
    request = ParseSkuRequest(
        marketplace=parser_mp,
        sku=link.article,
        product_url=link.url,
    )

    stock_client: WildberriesMobileClient | OzonMobileClient
    deep_client: WildberriesDeepClient | OzonDeepClient
    if link.marketplace is CompetitorMarketplace.WILDBERRIES:
        stock_client = WildberriesMobileClient(
            base_url=settings.stock_parser_wb_card_base_url,
            dest=settings.stock_parser_wb_dest,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
        )
        deep_client = WildberriesDeepClient(
            card_base_url=settings.stock_parser_wb_card_base_url,
            dest=settings.stock_parser_wb_dest,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
        )
    else:
        stock_client = OzonMobileClient(
            base_url=settings.stock_parser_ozon_api_base_url,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
        )
        deep_client = OzonDeepClient(
            base_url=settings.stock_parser_ozon_api_base_url,
            timeout_seconds=timeout,
            proxy_pool=proxy_pool,
        )

    try:
        try:
            snapshot = await stock_client.fetch_sku(request)
        except (ParserTransportError, ParserSchemaError) as exc:
            logger.warning("Stock parse failed for %s: %s", link.url, exc)
            snapshot = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stock parse unexpected failure for %s: %s", link.url, exc)
            snapshot = None

        try:
            deep = await deep_client.scrape_card(link)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Deep scrape failed for %s", link.url)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Marketplace scrape failed: {exc}",
            ) from exc
    finally:
        await stock_client.aclose()
        await deep_client.aclose()

    title = (deep.title or (snapshot.title if snapshot else None) or "").strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Marketplace returned an empty product title.",
        )

    price_kopecks = (
        deep.price_after_discount_kopecks
        if deep.price_after_discount_kopecks is not None
        else (snapshot.price_kopecks if snapshot else None)
    )
    price_before = (
        deep.price_before_discount_kopecks
        if deep.price_before_discount_kopecks is not None
        else (snapshot.price_before_discount_kopecks if snapshot else None)
    )
    currency = deep.currency or (snapshot.currency if snapshot else "RUB")
    total_stock = snapshot.total_stock if snapshot is not None else None

    return ParsedProductResponse(
        marketplace=link.marketplace.value,  # type: ignore[arg-type]
        sku=link.article,
        product_url=link.url,
        title=title,
        price_kopecks=price_kopecks,
        price_before_discount_kopecks=price_before,
        currency=currency,
        description=deep.description or None,
        characteristics=[
            ParsedCharacteristicDTO(name=row.name, value=row.value)
            for row in deep.specs
        ],
        image_urls=list(deep.photo_urls),
        total_stock=total_stock,
    )


@router.post(
    "/fetch",
    response_model=FetchProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch WB/Ozon product card by article or URL",
    description=(
        "Resolves ``input`` (URL or numeric article) with ``platform`` "
        "auto|wb|ozon, deep-scrapes title/brand/description/characteristics/"
        "max-res gallery, uploads images to internal S3, and caches the result "
        "in Redis for 1 hour."
    ),
    responses={
        404: {
            "description": "Product missing or marketplace blocked the request",
            "content": {
                "application/json": {
                    "example": {"error": PRODUCT_CARD_NOT_FOUND_ERROR},
                }
            },
        }
    },
)
async def fetch_product_v1(
    body: FetchProductRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        ProductCardParserService, Depends(_get_product_card_parser_service)
    ],
) -> FetchProductResponse | JSONResponse:
    del current_user  # auth gate only
    return await _fetch_product_card(body, service)


@parser_alias_router.post(
    "/fetch",
    response_model=FetchProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch WB/Ozon product card by article or URL",
    description=(
        "Alias of ``POST /api/v1/parser/fetch``. Accepts "
        "``{ input, platform: auto|wb|ozon }``, re-hosts gallery images in S3, "
        "and caches results in Redis for 1 hour."
    ),
    responses={
        404: {
            "description": "Product missing or marketplace blocked the request",
            "content": {
                "application/json": {
                    "example": {"error": PRODUCT_CARD_NOT_FOUND_ERROR},
                }
            },
        }
    },
)
async def fetch_product(
    body: FetchProductRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        ProductCardParserService, Depends(_get_product_card_parser_service)
    ],
) -> FetchProductResponse | JSONResponse:
    del current_user  # auth gate only
    return await _fetch_product_card(body, service)
