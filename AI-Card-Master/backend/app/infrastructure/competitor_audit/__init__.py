"""Competitor audit deep-scrape + Claude Vision package (WB/Ozon)."""

from app.infrastructure.competitor_audit.deep_scraper import CompetitorDeepScraper
from app.infrastructure.competitor_audit.image_fetcher import CompetitorCardImageFetcher
from app.infrastructure.competitor_audit.ozon_deep_client import OzonDeepClient
from app.infrastructure.competitor_audit.wb_deep_client import WildberriesDeepClient

__all__ = [
    "CompetitorCardImageFetcher",
    "CompetitorDeepScraper",
    "OzonDeepClient",
    "WildberriesDeepClient",
]
