"""Marketplace router for competitor deep scrapers."""

from __future__ import annotations

from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorProductLink,
)
from app.domain.stock_parser import ParserMarketplace
from app.infrastructure.competitor_audit.ozon_deep_client import OzonDeepClient
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient
from app.infrastructure.stock_parser.exceptions import ParserSchemaError


class CompetitorDeepScraper:
    """Dispatch deep scrape to WB or Ozon client by validated marketplace."""

    def __init__(
        self,
        *,
        wildberries: WildberriesDeepClient,
        ozon: OzonDeepClient,
    ) -> None:
        self._wildberries = wildberries
        self._ozon = ozon

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        if link.marketplace is CompetitorMarketplace.WILDBERRIES:
            return await self._wildberries.scrape_card(link)
        if link.marketplace is CompetitorMarketplace.OZON:
            return await self._ozon.scrape_card(link)
        raise ParserSchemaError(
            f"Unsupported marketplace: {link.marketplace}",
            marketplace=ParserMarketplace.WILDBERRIES,
        )

    async def aclose(self) -> None:
        await self._wildberries.aclose()
        await self._ozon.aclose()
