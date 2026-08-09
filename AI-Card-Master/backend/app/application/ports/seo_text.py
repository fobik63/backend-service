"""Ports for AI SEO marketplace copy generation."""

from __future__ import annotations

from typing import Protocol

from app.domain.seo_text import SeoTextContent, SeoTextGenerateRequest, SeoTokenUsage


class SeoTextProviderPort(Protocol):
    """Upstream LLM that produces SEO title, benefits, and description."""

    async def generate(
        self, request: SeoTextGenerateRequest
    ) -> tuple[SeoTextContent, SeoTokenUsage]:
        """Return structured SEO copy plus token usage."""
        ...

    async def aclose(self) -> None:
        """Release HTTP / client resources."""
        ...
