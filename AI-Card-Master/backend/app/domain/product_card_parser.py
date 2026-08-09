"""One-shot marketplace product-card fetch (WB / Ozon → structured JSON + S3).

Resolves an article or public product URL, deep-scrapes card metadata, and
exposes a Redis-cacheable payload with re-hosted gallery URLs.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.competitor_audit import (
    CompetitorMarketplace,
    CompetitorProductLink,
    parse_competitor_product_link,
)

PRODUCT_CARD_NOT_FOUND_ERROR = "Товар не найден или заблокирован"
REDIS_PRODUCT_CARD_TTL_SECONDS = 3600

_ARTICLE_RE = re.compile(r"^\d{5,15}$")
_WB_ARTICLE_URL = "https://www.wildberries.ru/catalog/{article}/detail.aspx"
_OZON_ARTICLE_URL = "https://www.ozon.ru/product/{article}/"


class ProductCardPlatform(StrEnum):
    """Client-facing marketplace hint for ``/api/parser/fetch``."""

    AUTO = "auto"
    WB = "wb"
    OZON = "ozon"


class ProductCardNotFoundError(Exception):
    """Article missing or marketplace blocked / throttled the scrape."""

    def __init__(self, message: str = PRODUCT_CARD_NOT_FOUND_ERROR) -> None:
        super().__init__(message)
        self.message = message


class ProductCardValidationError(ValueError):
    """Invalid ``input`` / ``platform`` combination."""


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProductCardCharacteristic(StrictDomainModel):
    name: str = Field(..., min_length=1, max_length=256)
    value: str = Field(..., min_length=1, max_length=2000)


class ProductCardFetchResult(StrictDomainModel):
    """Structured product card returned to API clients (S3 image links)."""

    marketplace: Literal["wildberries", "ozon"]
    sku: str = Field(..., min_length=1, max_length=64)
    product_url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(..., min_length=1, max_length=500)
    brand: str | None = Field(default=None, max_length=256)
    description: str | None = None
    characteristics: list[ProductCardCharacteristic] = Field(default_factory=list)
    image_urls: list[str] = Field(
        default_factory=list,
        description="Presigned / CDN URLs of images uploaded to internal S3.",
    )
    source_image_urls: list[str] = Field(
        default_factory=list,
        description="Original marketplace CDN URLs (max resolution).",
    )
    price_kopecks: int | None = Field(default=None, ge=0)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    cached: bool = False

    def to_cache_payload(self) -> dict[str, Any]:
        """JSON-safe dump for Redis (``cached`` always stored as False)."""

        payload = self.model_dump(mode="json")
        payload["cached"] = False
        return payload

    @classmethod
    def from_cache_payload(cls, payload: dict[str, Any]) -> ProductCardFetchResult:
        data = dict(payload)
        data["cached"] = True
        return cls.model_validate(data)


class ProductCardFetchRequest(StrictDomainModel):
    """Domain request for one product-card fetch."""

    input: str = Field(..., min_length=1, max_length=2048)
    platform: ProductCardPlatform = ProductCardPlatform.AUTO

    @field_validator("input", mode="before")
    @classmethod
    def _strip_input(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


def resolve_product_card_input(
    raw_input: str,
    platform: ProductCardPlatform = ProductCardPlatform.AUTO,
) -> CompetitorProductLink:
    """Resolve URL or bare article into a validated marketplace product link.

    - URL + ``auto`` → detect marketplace from host.
    - URL + ``wb``/``ozon`` → host must match the hint.
    - Bare article + ``wb``/``ozon`` → synthesize a canonical product URL.
    - Bare article + ``auto`` → validation error (platform required).
    """

    cleaned = (raw_input or "").strip()
    if not cleaned:
        raise ProductCardValidationError("input must not be empty.")
    if len(cleaned) > 2048:
        raise ProductCardValidationError("input exceeds maximum length of 2048.")

    if _looks_like_url(cleaned):
        url = cleaned
        if "://" not in url:
            url = f"https://{url}"
        try:
            link = parse_competitor_product_link(url)
        except ValueError as exc:
            raise ProductCardValidationError(str(exc)) from exc
        _assert_platform_matches(link.marketplace, platform)
        return link

    article = _extract_article_digits(cleaned)
    if article is None:
        raise ProductCardValidationError(
            "input must be a Wildberries/Ozon product URL or a numeric article."
        )

    if platform is ProductCardPlatform.AUTO:
        raise ProductCardValidationError(
            "Bare article requires platform 'wb' or 'ozon' (auto only works with URLs)."
        )

    if platform is ProductCardPlatform.WB:
        return CompetitorProductLink(
            url=_WB_ARTICLE_URL.format(article=article),
            marketplace=CompetitorMarketplace.WILDBERRIES,
            article=article,
        )

    return CompetitorProductLink(
        url=_OZON_ARTICLE_URL.format(article=article),
        marketplace=CompetitorMarketplace.OZON,
        article=article,
    )


def redis_product_card_cache_key(
    *,
    marketplace: CompetitorMarketplace | str,
    article: str,
) -> str:
    """Stable Redis key for a marketplace SKU card (TTL 1 hour)."""

    mp = (
        marketplace.value
        if isinstance(marketplace, CompetitorMarketplace)
        else str(marketplace).strip().casefold()
    )
    sku = str(article).strip()
    digest = hashlib.sha256(f"{mp}:{sku}".encode("utf-8")).hexdigest()[:24]
    return f"parser:product_card:{mp}:{sku}:{digest}"


def _looks_like_url(value: str) -> bool:
    lowered = value.casefold()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").casefold()
    return bool(
        host
        and (
            "wildberries.ru" in host
            or host.endswith("wb.ru")
            or host == "wb.ru"
            or "ozon.ru" in host
        )
    )


def _extract_article_digits(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if _ARTICLE_RE.fullmatch(digits or ""):
        return digits
    # Allow "nm-12345678" / "SKU 1234567890" styles.
    match = re.search(r"(\d{5,15})", value)
    if match is not None and _ARTICLE_RE.fullmatch(match.group(1)):
        return match.group(1)
    return None


def _assert_platform_matches(
    marketplace: CompetitorMarketplace,
    platform: ProductCardPlatform,
) -> None:
    if platform is ProductCardPlatform.AUTO:
        return
    expected = (
        CompetitorMarketplace.WILDBERRIES
        if platform is ProductCardPlatform.WB
        else CompetitorMarketplace.OZON
    )
    if marketplace is not expected:
        raise ProductCardValidationError(
            f"platform '{platform.value}' does not match URL marketplace "
            f"'{marketplace.value}'."
        )
