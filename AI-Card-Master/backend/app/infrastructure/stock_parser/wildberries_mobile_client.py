"""Wildberries mobile card JSON client (no Selenium / no HTML scraping).

Uses the same public card detail JSON consumed by the WB iOS/Android apps.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.domain.stock_parser import (
    ParsedSkuSnapshot,
    ParserMarketplace,
    ParseSkuRequest,
    StockLevel,
)
from app.infrastructure.stock_parser.exceptions import ParserSchemaError
from app.infrastructure.stock_parser.http_transport import MobileJsonTransport
from app.infrastructure.stock_parser.json_schema_guard import (
    assert_wildberries_card_payload,
)
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

# Mobile / light card API (structure changes slower than www HTML).
DEFAULT_WB_CARD_BASE = "https://card.wb.ru"


class WildberriesMobileClient:
    """Fetch SKU card + stocks via WB mobile JSON endpoints."""

    marketplace = ParserMarketplace.WILDBERRIES

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_WB_CARD_BASE,
        dest: int = -1257786,
        timeout_seconds: float = 20.0,
        proxy_pool: ProxyPool | None = None,
        transport: MobileJsonTransport | None = None,
        request_delay_min_seconds: float | None = None,
        request_delay_max_seconds: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dest = dest
        transport_kwargs: dict[str, float] = {}
        if request_delay_min_seconds is not None:
            transport_kwargs["request_delay_min_seconds"] = request_delay_min_seconds
        if request_delay_max_seconds is not None:
            transport_kwargs["request_delay_max_seconds"] = request_delay_max_seconds
        self._transport = transport or MobileJsonTransport(
            marketplace=self.marketplace,
            proxy_pool=proxy_pool,
            timeout_seconds=timeout_seconds,
            **transport_kwargs,
        )

    async def fetch_sku(self, request: ParseSkuRequest) -> ParsedSkuSnapshot:
        if request.marketplace is not ParserMarketplace.WILDBERRIES:
            raise ParserSchemaError(
                "WildberriesMobileClient received non-WB request",
                marketplace=self.marketplace,
            )
        nm_id = _extract_wb_nm(request.sku, request.product_url)
        url = f"{self._base_url}/cards/v1/detail"
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": self._dest,
            "nm": nm_id,
        }
        payload = await self._transport.get_json(url, params=params)
        product = assert_wildberries_card_payload(payload)
        return _map_wb_product(
            product,
            sku=str(nm_id),
            product_url=request.product_url,
            raw_payload=payload,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()


def _extract_wb_nm(sku: str, product_url: str | None) -> int:
    digits = "".join(ch for ch in sku if ch.isdigit())
    if digits:
        return int(digits)
    if product_url:
        path = urlparse(product_url).path
        for part in reversed(path.rstrip("/").split("/")):
            if part.isdigit():
                return int(part)
    raise ParserSchemaError(
        f"Cannot resolve Wildberries nm id from sku={sku!r} url={product_url!r}",
        marketplace=ParserMarketplace.WILDBERRIES,
        missing_keys=("nm",),
    )


def _map_wb_product(
    product: dict[str, Any],
    *,
    sku: str,
    product_url: str | None,
    raw_payload: dict[str, Any],
) -> ParsedSkuSnapshot:
    stocks: list[StockLevel] = []
    for size in product.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        for stock in size.get("stocks") or []:
            if not isinstance(stock, dict):
                continue
            wh = stock.get("wh")
            qty = stock.get("qty")
            if wh is None or qty is None:
                continue
            stocks.append(
                StockLevel(
                    warehouse_id=str(wh),
                    quantity=max(0, int(qty)),
                    warehouse_name=None,
                )
            )

    sale = int(product.get("salePriceU") or 0)
    price = int(product.get("priceU") or sale)
    title = str(product.get("name") or "").strip() or f"WB {sku}"
    return ParsedSkuSnapshot(
        marketplace=ParserMarketplace.WILDBERRIES,
        sku=sku,
        product_url=product_url,
        title=title[:500],
        price_kopecks=sale,
        price_before_discount_kopecks=price if price != sale else None,
        currency="RUB",
        stocks=tuple(stocks),
        raw_payload=raw_payload,
    )
