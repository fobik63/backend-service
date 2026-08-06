"""Composition root for Marketplace Data Bridge."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.marketplace_bridge_service import MarketplaceBridgeService
from app.core.config import get_settings
from app.domain.marketplace_bridge import BridgePlatform
from app.infrastructure.marketplaces.ozon_analytics_client import OzonAnalyticsClient
from app.infrastructure.marketplaces.wildberries_analytics_client import (
    WildberriesAnalyticsClient,
)
from app.infrastructure.persistence.export_repository import ExportRepository


def build_marketplace_bridge_service(
    db_session: AsyncSession,
) -> MarketplaceBridgeService:
    """Wire credential store + WB/Ozon analytics clients for HTTP handlers."""

    settings = get_settings()
    secret = settings.marketplace_credentials_secret.get_secret_value()
    if not secret.strip():
        secret = settings.jwt_secret_key.get_secret_value()
    timeout = settings.marketplace_bridge_timeout_seconds
    return MarketplaceBridgeService(
        ExportRepository(db_session),
        {
            BridgePlatform.WILDBERRIES: WildberriesAnalyticsClient(
                base_url=settings.wildberries_statistics_api_base_url,
                timeout_seconds=timeout,
            ),
            BridgePlatform.OZON: OzonAnalyticsClient(
                base_url=settings.ozon_seller_api_base_url,
                timeout_seconds=timeout,
            ),
        },
        encryption_secret=secret,
    )
