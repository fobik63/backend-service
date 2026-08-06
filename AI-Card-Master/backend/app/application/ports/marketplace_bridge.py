"""Ports for Marketplace Data Bridge (credentials + seller analytics APIs)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.export import MarketplaceCredentialView, MarketplacePlatform
from app.domain.marketplace_bridge import (
    BridgePlatform,
    OrdersMetrics,
    PeriodWindow,
    SalesMetrics,
    StocksMetrics,
)


class BridgeCredentialPort(Protocol):
    """Read encrypted marketplace credentials without exposing plaintext."""

    async def get_credentials_ciphertext(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> str | None:
        """Return ciphertext or None when the platform is not connected."""

    async def list_credentials(self, user_id: UUID) -> tuple[MarketplaceCredentialView, ...]:
        """List configured platforms (metadata only)."""


class MarketplaceAnalyticsPort(Protocol):
    """Fetch sales / stocks / orders for one marketplace seller account."""

    platform: BridgePlatform

    async def fetch_sales(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> SalesMetrics:
        """Aggregate sales (revenue + count) inside the window."""

    async def fetch_stocks(
        self,
        *,
        credentials: dict[str, str],
    ) -> StocksMetrics:
        """Point-in-time stock snapshot across warehouses."""

    async def fetch_orders(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> OrdersMetrics:
        """Aggregate orders (and cancellations) inside the window."""
