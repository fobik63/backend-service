"""Application use cases for Marketplace Data Bridge (cabinet sales dashboard)."""

from __future__ import annotations

from uuid import UUID

from app.application.ports.marketplace_bridge import (
    BridgeCredentialPort,
    MarketplaceAnalyticsPort,
)
from app.core.credential_crypto import CredentialCryptoError, decrypt_credentials
from app.domain.export import MarketplacePlatform
from app.domain.marketplace_bridge import (
    BridgePlatform,
    MarketplaceDashboardView,
    MarketplaceDataPeriod,
    PeriodWindow,
    PlatformDataSlice,
    build_aggregated_totals,
    empty_orders,
    empty_sales,
    empty_stocks,
    resolve_period_window,
)


class MarketplaceBridgeError(Exception):
    """Base Marketplace Data Bridge failure."""


class MarketplaceBridgeValidationError(MarketplaceBridgeError):
    """Invalid period or crypto configuration."""


class MarketplaceBridgeNotFoundError(MarketplaceBridgeError):
    """Requested marketplace credentials are missing."""


_BRIDGE_TO_EXPORT: dict[BridgePlatform, MarketplacePlatform] = {
    BridgePlatform.WILDBERRIES: MarketplacePlatform.WILDBERRIES,
    BridgePlatform.OZON: MarketplacePlatform.OZON,
}


class MarketplaceBridgeService:
    """Decrypt stored keys and aggregate WB/Ozon sales, stocks, and orders."""

    def __init__(
        self,
        credentials: BridgeCredentialPort,
        analytics: dict[BridgePlatform, MarketplaceAnalyticsPort],
        *,
        encryption_secret: str,
    ) -> None:
        if not encryption_secret.strip():
            raise ValueError("Marketplace credential encryption secret is not configured.")
        self._credentials = credentials
        self._analytics = analytics
        self._encryption_secret = encryption_secret

    async def get_dashboard(
        self,
        *,
        user_id: UUID,
        period: MarketplaceDataPeriod,
    ) -> MarketplaceDashboardView:
        """Aggregate sales / stocks / orders for the personal cabinet."""

        window = resolve_period_window(period)
        slices: list[PlatformDataSlice] = []
        for platform in (BridgePlatform.WILDBERRIES, BridgePlatform.OZON):
            slices.append(
                await self._build_platform_slice(
                    user_id=user_id,
                    platform=platform,
                    window=window,
                )
            )
        platforms = tuple(slices)
        return MarketplaceDashboardView(
            period=window.period,
            date_from=window.date_from,
            date_to=window.date_to,
            platforms=platforms,
            totals=build_aggregated_totals(platforms),
        )

    async def get_platform_metrics(
        self,
        *,
        user_id: UUID,
        platform: BridgePlatform,
        period: MarketplaceDataPeriod,
    ) -> PlatformDataSlice:
        """Fetch one marketplace slice (raises if credentials are missing)."""

        window = resolve_period_window(period)
        slice_ = await self._build_platform_slice(
            user_id=user_id,
            platform=platform,
            window=window,
        )
        if not slice_.connected:
            raise MarketplaceBridgeNotFoundError(
                f"Connect {platform.value} API credentials before loading analytics."
            )
        return slice_

    async def _build_platform_slice(
        self,
        *,
        user_id: UUID,
        platform: BridgePlatform,
        window: PeriodWindow,
    ) -> PlatformDataSlice:
        export_platform = _BRIDGE_TO_EXPORT[platform]
        ciphertext = await self._credentials.get_credentials_ciphertext(
            user_id=user_id,
            platform=export_platform,
        )
        if ciphertext is None:
            return PlatformDataSlice(
                platform=platform,
                connected=False,
                sales=empty_sales(),
                stocks=empty_stocks(),
                orders=empty_orders(),
                error=None,
            )

        try:
            secrets = decrypt_credentials(ciphertext, secret=self._encryption_secret)
        except CredentialCryptoError as exc:
            return PlatformDataSlice(
                platform=platform,
                connected=True,
                sales=empty_sales(),
                stocks=empty_stocks(),
                orders=empty_orders(),
                error=str(exc),
            )

        client = self._analytics.get(platform)
        if client is None:
            return PlatformDataSlice(
                platform=platform,
                connected=True,
                sales=empty_sales(),
                stocks=empty_stocks(),
                orders=empty_orders(),
                error=f"No analytics adapter registered for {platform.value}.",
            )

        try:
            sales = await client.fetch_sales(credentials=secrets, window=window)
            stocks = await client.fetch_stocks(credentials=secrets)
            orders = await client.fetch_orders(credentials=secrets, window=window)
        except Exception as exc:  # noqa: BLE001 — upstream seller APIs are unreliable
            return PlatformDataSlice(
                platform=platform,
                connected=True,
                sales=empty_sales(),
                stocks=empty_stocks(),
                orders=empty_orders(),
                error=str(exc)[:500],
            )

        return PlatformDataSlice(
            platform=platform,
            connected=True,
            sales=sales,
            stocks=stocks,
            orders=orders,
            error=None,
        )
