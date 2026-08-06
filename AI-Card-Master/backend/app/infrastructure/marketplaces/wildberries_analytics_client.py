"""Wildberries Statistics API adapter: sales, stocks, and orders."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.export import MarketplaceSellerError
from app.domain.marketplace_bridge import (
    BridgePlatform,
    OrdersMetrics,
    PeriodWindow,
    SalesMetrics,
    StocksMetrics,
    in_period_window,
    parse_marketplace_datetime,
)

logger = logging.getLogger(__name__)

WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"


class WildberriesAnalyticsClient:
    """Read supplier sales / stocks / orders via WB Statistics API."""

    platform = BridgePlatform.WILDBERRIES

    def __init__(
        self,
        *,
        base_url: str = WB_STATISTICS_BASE,
        timeout_seconds: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    async def fetch_sales(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> SalesMetrics:
        rows = await self._get_rows(
            path="/api/v1/supplier/sales",
            token=credentials["api_token"],
            date_from=window.date_from.isoformat(),
        )
        count = 0
        revenue = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamped = parse_marketplace_datetime(row.get("date") or row.get("lastChangeDate"))
            if not in_period_window(stamped, window=window):
                continue
            if bool(row.get("isCancel") or row.get("cancelDate")):
                continue
            count += 1
            revenue += _as_float(row.get("forPay") or row.get("finishedPrice") or row.get("priceWithDisc"))
        return SalesMetrics(count=count, revenue=round(revenue, 2), currency="RUB")

    async def fetch_stocks(
        self,
        *,
        credentials: dict[str, str],
    ) -> StocksMetrics:
        # Stocks endpoint requires dateFrom; use a far-past stamp to get the full snapshot.
        rows = await self._get_rows(
            path="/api/v1/supplier/stocks",
            token=credentials["api_token"],
            date_from="2019-01-01T00:00:00",
        )
        sku_keys: set[str] = set()
        total_quantity = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            sku = str(row.get("nmId") or row.get("barcode") or row.get("supplierArticle") or "")
            if sku:
                sku_keys.add(sku)
            total_quantity += max(0, int(_as_float(row.get("quantity") or row.get("quantityFull"))))
        return StocksMetrics(sku_count=len(sku_keys), total_quantity=total_quantity)

    async def fetch_orders(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> OrdersMetrics:
        rows = await self._get_rows(
            path="/api/v1/supplier/orders",
            token=credentials["api_token"],
            date_from=window.date_from.isoformat(),
        )
        count = 0
        cancelled = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamped = parse_marketplace_datetime(row.get("date") or row.get("lastChangeDate"))
            if not in_period_window(stamped, window=window):
                continue
            count += 1
            if bool(row.get("isCancel") or row.get("cancelDate")):
                cancelled += 1
        return OrdersMetrics(count=count, cancelled_count=cancelled)

    async def _get_rows(
        self,
        *,
        path: str,
        token: str,
        date_from: str,
    ) -> list[Any]:
        async with self._http() as client:
            try:
                response = await client.get(
                    f"{self._base_url}{path}",
                    headers=_wb_headers(token),
                    params={"dateFrom": date_from, "flag": 0},
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplaceSellerError(
                    f"Wildberries analytics timed out or is unreachable ({path}): {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplaceSellerError(
                    f"Wildberries analytics transport error ({path}): {exc}"
                ) from exc
            if response.status_code >= 400:
                raise MarketplaceSellerError(
                    f"Wildberries {path} failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            try:
                body: Any = response.json()
            except ValueError as exc:
                raise MarketplaceSellerError(
                    f"Wildberries {path} returned non-JSON body."
                ) from exc
        if body is None:
            return []
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            return body["data"]
        logger.warning("Unexpected Wildberries %s payload type: %s", path, type(body).__name__)
        return []

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


def _wb_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _as_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class _NullContextClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None
