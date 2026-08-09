"""Composition root for marketplace publish + user seller credentials."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.marketplace_publish_service import MarketplacePublishService
from app.core.config import Settings, get_settings
from app.domain.marketplace_publish import PublishPlatform
from app.infrastructure.marketplaces.ozon_client import OzonSellerClient
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient
from app.infrastructure.persistence.marketplace_publish_repository import (
    MarketplacePublishRepository,
)


def build_marketplace_publish_service(
    db_session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> MarketplacePublishService:
    """Wire encrypted user credentials + WB/Ozon publish adapters."""

    cfg = settings or get_settings()
    secret = cfg.marketplace_credentials_secret.get_secret_value()
    if not secret.strip():
        secret = cfg.jwt_secret_key.get_secret_value()

    repository = MarketplacePublishRepository(db_session, encryption_secret=secret)
    return MarketplacePublishService(
        repository,
        clients={
            PublishPlatform.WILDBERRIES: WildberriesSellerClient(
                base_url=cfg.wildberries_content_api_base_url,
                timeout_seconds=cfg.marketplace_export_timeout_seconds,
            ),
            PublishPlatform.OZON: OzonSellerClient(
                base_url=cfg.ozon_seller_api_base_url,
                timeout_seconds=cfg.marketplace_export_timeout_seconds,
            ),
        },
        history=repository,
    )
