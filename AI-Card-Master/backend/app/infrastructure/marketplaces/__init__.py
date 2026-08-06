"""Marketplace seller and advertising cabinet adapters."""

from __future__ import annotations

from app.infrastructure.marketplaces.ads_clients import (
    OzonAdsClient,
    WildberriesAdsClient,
    build_marketplace_ads_client,
)
from app.infrastructure.marketplaces.amazon_client import AmazonSellerClient
from app.infrastructure.marketplaces.image_assets import S3ImageAssetAdapter
from app.infrastructure.marketplaces.ozon_client import OzonSellerClient
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient

__all__ = [
    "AmazonSellerClient",
    "OzonAdsClient",
    "OzonSellerClient",
    "S3ImageAssetAdapter",
    "WildberriesAdsClient",
    "WildberriesSellerClient",
    "build_marketplace_ads_client",
]
