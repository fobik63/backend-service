"""Ozon Seller API adapter: sales, stocks, and orders analytics."""

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

OZON_API_BASE = "https://api-seller.ozon.ru"


class OzonAnalyticsClient:
    """Read Ozon finance transactions, stock levels, and FBS/FBO postings."""

    platform = BridgePlatform.OZON

    def __init__(
        self,
        *,
        base_url: str = OZON_API_BASE,
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
        rows = await self._list_finance_transactions(
            credentials=credentials,
            window=window,
        )
        count = 0
        revenue = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            operation_type = str(row.get("operation_type") or "").lower()
            # Keep delivered / sale-like accruals; skip returns and services.
            if "return" in operation_type or "service" in operation_type:
                continue
            amount = _as_float(row.get("amount"))
            if amount <= 0 and "sale" not in operation_type and "accruals" not in operation_type:
                # Still count orders with zero amount when posting markers exist.
                if not row.get("posting"):
                    continue
            count += 1
            revenue += max(0.0, amount)
        return SalesMetrics(count=count, revenue=round(revenue, 2), currency="RUB")

    async def fetch_stocks(
        self,
        *,
        credentials: dict[str, str],
    ) -> StocksMetrics:
        items = await self._list_stock_items(credentials=credentials)
        sku_keys: set[str] = set()
        total_quantity = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            offer_id = str(item.get("offer_id") or item.get("product_id") or "")
            if offer_id:
                sku_keys.add(offer_id)
            stocks = item.get("stocks")
            if isinstance(stocks, list):
                for stock in stocks:
                    if not isinstance(stock, dict):
                        continue
                    present = int(_as_float(stock.get("present")))
                    reserved = int(_as_float(stock.get("reserved")))
                    total_quantity += max(0, present - reserved)
            else:
                total_quantity += max(0, int(_as_float(item.get("present") or item.get("quantity"))))
        return StocksMetrics(sku_count=len(sku_keys), total_quantity=total_quantity)

    async def fetch_orders(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> OrdersMetrics:
        fbs = await self._list_postings(
            credentials=credentials,
            path="/v3/posting/fbs/list",
            window=window,
        )
        fbo = await self._list_postings(
            credentials=credentials,
            path="/v2/posting/fbo/list",
            window=window,
        )
        count = 0
        cancelled = 0
        for row in (*fbs, *fbo):
            if not isinstance(row, dict):
                continue
            stamped = parse_marketplace_datetime(
                row.get("created_at") or row.get("in_process_at")
            )
            if not in_period_window(stamped, window=window):
                continue
            count += 1
            status = str(row.get("status") or "").lower()
            if status in {"cancelled", "canceled"}:
                cancelled += 1
        return OrdersMetrics(count=count, cancelled_count=cancelled)

    async def _list_finance_transactions(
        self,
        *,
        credentials: dict[str, str],
        window: PeriodWindow,
    ) -> list[Any]:
        page = 1
        collected: list[Any] = []
        while page <= 20:
            body = await self._post_json(
                path="/v3/finance/transaction/list",
                credentials=credentials,
                payload={
                    "filter": {
                        "date": {
                            "from": window.date_from.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            "to": window.date_to.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        },
                        "operation_type": [],
                        "posting_number": "",
                        "transaction_type": "all",
                    },
                    "page": page,
                    "page_size": 1000,
                },
            )
            result = body.get("result") if isinstance(body, dict) else None
            operations = []
            if isinstance(result, dict):
                operations = result.get("operations") or []
            if not isinstance(operations, list) or not operations:
                break
            collected.extend(operations)
            page_count = int(_as_float(result.get("page_count"))) if isinstance(result, dict) else 1
            if page >= page_count:
                break
            page += 1
        return collected

    async def _list_stock_items(self, *, credentials: dict[str, str]) -> list[Any]:
        collected: list[Any] = []
        last_id = ""
        for _ in range(50):
            payload: dict[str, Any] = {
                "filter": {
                    "visibility": "ALL",
                },
                "limit": 1000,
            }
            if last_id:
                payload["last_id"] = last_id
            body = await self._post_json(
                path="/v4/product/info/stocks",
                credentials=credentials,
                payload=payload,
            )
            result = body.get("result") if isinstance(body, dict) else None
            items: list[Any] = []
            next_last_id = ""
            if isinstance(result, dict):
                raw_items = result.get("items") or []
                if isinstance(raw_items, list):
                    items = raw_items
                next_last_id = str(result.get("last_id") or "")
            if not items:
                break
            collected.extend(items)
            if not next_last_id or next_last_id == last_id:
                break
            last_id = next_last_id
        return collected

    async def _list_postings(
        self,
        *,
        credentials: dict[str, str],
        path: str,
        window: PeriodWindow,
    ) -> list[Any]:
        since = window.date_from.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to = window.date_to.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        collected: list[Any] = []
        offset = 0
        for _ in range(20):
            body = await self._post_json(
                path=path,
                credentials=credentials,
                payload={
                    "dir": "ASC",
                    "filter": {
                        "since": since,
                        "to": to,
                        "status": "",
                    },
                    "limit": 1000,
                    "offset": offset,
                    "with": {"analytics_data": False, "financial_data": False},
                },
            )
            result = body.get("result") if isinstance(body, dict) else None
            postings: list[Any] = []
            has_next = False
            if isinstance(result, dict):
                raw = result.get("postings") or []
                if isinstance(raw, list):
                    postings = raw
                has_next = bool(result.get("has_next"))
            if not postings:
                break
            collected.extend(postings)
            if not has_next:
                break
            offset += len(postings)
        return collected

    async def _post_json(
        self,
        *,
        path: str,
        credentials: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {
            "Client-Id": credentials["client_id"],
            "Api-Key": credentials["api_key"],
            "Content-Type": "application/json",
        }
        async with self._http() as client:
            response = await client.post(
                f"{self._base_url}{path}",
                headers=headers,
                json=payload,
            )
            if response.status_code >= 400:
                raise MarketplaceSellerError(
                    f"Ozon {path} failed ({response.status_code}): {response.text[:300]}"
                )
            body: Any = response.json()
        if not isinstance(body, dict):
            raise MarketplaceSellerError(f"Ozon {path} returned a non-object payload.")
        return body

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


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
