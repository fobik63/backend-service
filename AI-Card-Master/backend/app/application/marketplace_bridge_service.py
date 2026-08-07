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
from app.infrastructure.http_resilience import gather_bounded, gather_independent


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

_DASHBOARD_PLATFORMS: tuple[BridgePlatform, ...] = (
    BridgePlatform.WILDBERRIES,
    BridgePlatform.OZON,
)


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
        """Aggregate sales / stocks / orders for the personal cabinet.

        Prompt-efficiency shape (2 passes):
        1) one batched credentials read from DB
        2) one bounded gather over platforms, each fanning sales/stocks/orders
        """

        window = resolve_period_window(period)
        export_platforms = tuple(_BRIDGE_TO_EXPORT[p] for p in _DASHBOARD_PLATFORMS)
        cipher_by_export = await self._credentials.get_credentials_ciphertext_batch(
            user_id=user_id,
            platforms=export_platforms,
        )

        results = await gather_bounded(
            _DASHBOARD_PLATFORMS,
            lambda platform: self._build_platform_slice_from_cipher(
                platform=platform,
                window=window,
                ciphertext=cipher_by_export.get(_BRIDGE_TO_EXPORT[platform]),
            ),
            limit=len(_DASHBOARD_PLATFORMS),
            return_exceptions=True,
        )

        slices: list[PlatformDataSlice] = []
        for platform, result in zip(_DASHBOARD_PLATFORMS, results, strict=True):
            if isinstance(result, BaseException):
                slices.append(
                    PlatformDataSlice(
                        platform=platform,
                        connected=True,
                        sales=empty_sales(),
                        stocks=empty_stocks(),
                        orders=empty_orders(),
                        error=str(result)[:500],
                    )
                )
            else:
                slices.append(result)

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
        return await self._build_platform_slice_from_cipher(
            platform=platform,
            window=window,
            ciphertext=ciphertext,
        )

    async def _build_platform_slice_from_cipher(
        self,
        *,
        platform: BridgePlatform,
        window: PeriodWindow,
        ciphertext: str | None,
    ) -> PlatformDataSlice:
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

        # One gather: sales + stocks + orders stay isolated per metric.
        sales_r, stocks_r, orders_r = await gather_independent(
            lambda: client.fetch_sales(credentials=secrets, window=window),
            lambda: client.fetch_stocks(credentials=secrets),
            lambda: client.fetch_orders(credentials=secrets, window=window),
        )

        errors: list[str] = []
        sales = empty_sales()
        stocks = empty_stocks()
        orders = empty_orders()
        if isinstance(sales_r, BaseException):
            errors.append(f"sales: {sales_r}")
        else:
            sales = sales_r
        if isinstance(stocks_r, BaseException):
            errors.append(f"stocks: {stocks_r}")
        else:
            stocks = stocks_r
        if isinstance(orders_r, BaseException):
            errors.append(f"orders: {orders_r}")
        else:
            orders = orders_r

        if errors and len(errors) == 3:
            # Full upstream outage — same UX as the previous single try/except.
            return PlatformDataSlice(
                platform=platform,
                connected=True,
                sales=empty_sales(),
                stocks=empty_stocks(),
                orders=empty_orders(),
                error="; ".join(errors)[:500],
            )

        return PlatformDataSlice(
            platform=platform,
            connected=True,
            sales=sales,
            stocks=stocks,
            orders=orders,
            error="; ".join(errors)[:500] if errors else None,
        )
