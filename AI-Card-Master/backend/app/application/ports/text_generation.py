"""Provider interfaces for AI marketplace text generation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.generation import MarketplaceTextContent, SlideWorkItem


@runtime_checkable
class MarketplaceTextProviderPort(Protocol):
    """Analyze generated images and return marketplace-ready product copy."""

    async def generate_marketplace_text(
        self,
        *,
        product_category: str | None,
        slides: tuple[SlideWorkItem, ...],
        images: tuple[bytes, ...],
    ) -> MarketplaceTextContent:
        """Return SEO title, long selling description, and key advantages."""
