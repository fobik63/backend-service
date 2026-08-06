"""Marketplace Data Bridge API: cabinet sales / stocks / orders dashboard."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.marketplace_bridge_service import (
    MarketplaceBridgeError,
    MarketplaceBridgeNotFoundError,
    MarketplaceBridgeService,
    MarketplaceBridgeValidationError,
)
from app.domain.marketplace_bridge import (
    AggregatedTotals,
    BridgePlatform,
    MarketplaceDashboardView,
    MarketplaceDataPeriod,
    OrdersMetrics,
    PlatformDataSlice,
    SalesMetrics,
    StocksMetrics,
)
from app.infrastructure.marketplace_bridge_factory import build_marketplace_bridge_service
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/marketplace-bridge", tags=["marketplace-bridge"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SalesMetricsResponse(StrictAPIModel):
    count: int = Field(ge=0)
    revenue: float
    currency: str


class StocksMetricsResponse(StrictAPIModel):
    sku_count: int = Field(ge=0)
    total_quantity: int = Field(ge=0)


class OrdersMetricsResponse(StrictAPIModel):
    count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)


class PlatformSliceResponse(StrictAPIModel):
    platform: BridgePlatform
    connected: bool
    sales: SalesMetricsResponse
    stocks: StocksMetricsResponse
    orders: OrdersMetricsResponse
    error: str | None = None


class TotalsResponse(StrictAPIModel):
    sales: SalesMetricsResponse
    stocks: StocksMetricsResponse
    orders: OrdersMetricsResponse
    connected_platforms: int = Field(ge=0)


class DashboardResponse(StrictAPIModel):
    period: MarketplaceDataPeriod
    date_from: str
    date_to: str
    platforms: list[PlatformSliceResponse]
    totals: TotalsResponse


def get_marketplace_bridge_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> MarketplaceBridgeService:
    return build_marketplace_bridge_service(db_session)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_marketplace_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MarketplaceBridgeService, Depends(get_marketplace_bridge_service)],
    period: MarketplaceDataPeriod = Query(
        default=MarketplaceDataPeriod.WEEK,
        description="Relative window: day (24h), week (7d), or month (30d).",
    ),
) -> DashboardResponse:
    """Aggregate WB + Ozon sales, stocks, and orders for the personal cabinet."""

    try:
        view = await service.get_dashboard(user_id=current_user.id, period=period)
    except MarketplaceBridgeError as exc:
        raise _map_bridge_error(exc) from exc
    return _dashboard_response(view)


@router.get(
    "/platforms/{platform}",
    response_model=PlatformSliceResponse,
)
async def get_platform_bridge_metrics(
    platform: BridgePlatform,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MarketplaceBridgeService, Depends(get_marketplace_bridge_service)],
    period: MarketplaceDataPeriod = Query(default=MarketplaceDataPeriod.WEEK),
) -> PlatformSliceResponse:
    """Return sales / stocks / orders for one connected marketplace."""

    try:
        slice_ = await service.get_platform_metrics(
            user_id=current_user.id,
            platform=platform,
            period=period,
        )
    except MarketplaceBridgeError as exc:
        raise _map_bridge_error(exc) from exc
    return _platform_response(slice_)


def _dashboard_response(view: MarketplaceDashboardView) -> DashboardResponse:
    return DashboardResponse(
        period=view.period,
        date_from=view.date_from.isoformat(),
        date_to=view.date_to.isoformat(),
        platforms=[_platform_response(item) for item in view.platforms],
        totals=_totals_response(view.totals),
    )


def _platform_response(slice_: PlatformDataSlice) -> PlatformSliceResponse:
    return PlatformSliceResponse(
        platform=slice_.platform,
        connected=slice_.connected,
        sales=_sales_response(slice_.sales),
        stocks=_stocks_response(slice_.stocks),
        orders=_orders_response(slice_.orders),
        error=slice_.error,
    )


def _totals_response(totals: AggregatedTotals) -> TotalsResponse:
    return TotalsResponse(
        sales=_sales_response(totals.sales),
        stocks=_stocks_response(totals.stocks),
        orders=_orders_response(totals.orders),
        connected_platforms=totals.connected_platforms,
    )


def _sales_response(metrics: SalesMetrics) -> SalesMetricsResponse:
    return SalesMetricsResponse(
        count=metrics.count,
        revenue=metrics.revenue,
        currency=metrics.currency,
    )


def _stocks_response(metrics: StocksMetrics) -> StocksMetricsResponse:
    return StocksMetricsResponse(
        sku_count=metrics.sku_count,
        total_quantity=metrics.total_quantity,
    )


def _orders_response(metrics: OrdersMetrics) -> OrdersMetricsResponse:
    return OrdersMetricsResponse(
        count=metrics.count,
        cancelled_count=metrics.cancelled_count,
    )


def _map_bridge_error(exc: MarketplaceBridgeError) -> HTTPException:
    if isinstance(exc, MarketplaceBridgeNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MarketplaceBridgeValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    logger.exception("Marketplace bridge failure: %s", exc)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc) or "Marketplace bridge request failed.",
    )
