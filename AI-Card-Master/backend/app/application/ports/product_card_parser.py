"""Ports for one-shot marketplace product-card fetch (+ S3 re-host)."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorProductLink,
)


class ProductCardScraperPort(Protocol):
    """Deep scrape of one WB/Ozon product card."""

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        """Fetch title / brand / specs / gallery for one validated link."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class ProductCardImageDownloaderPort(Protocol):
    """Download marketplace gallery images for S3 upload."""

    async def fetch_urls(
        self,
        *,
        urls: list[str],
        max_images: int = 40,
    ) -> tuple[tuple[bytes, str, str], ...]:
        """Return ((bytes, mime_type, source_url), ...) up to ``max_images``."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class ProductCardObjectStoragePort(Protocol):
    """Upload product gallery bytes into the internal S3 bucket."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> Any:
        """Upload and optionally return an object with ``presigned_url``."""


class ProductCardCachePort(Protocol):
    """Redis JSON cache for product-card fetch results."""

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return cached payload or ``None`` on miss / soft Redis failure."""

    async def set(
        self, key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        """Store payload with TTL (fail-open on Redis errors)."""
