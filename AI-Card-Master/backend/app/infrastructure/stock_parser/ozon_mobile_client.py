"""Ozon mobile / composer JSON client (no Selenium / no HTML scraping).

Hits composer-api page JSON used by the Ozon iOS/Android apps.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.domain.stock_parser import (
    ParseSkuRequest,
    ParsedSkuSnapshot,
    ParserMarketplace,
    StockLevel,
)
from app.infrastructure.stock_parser.exceptions import ParserSchemaError
from app.infrastructure.stock_parser.http_transport import MobileJsonTransport
from app.infrastructure.stock_parser.json_schema_guard import assert_ozon_product_payload
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

DEFAULT_OZON_COMPOSER_BASE = "https://api.ozon.ru"
_SKU_IN_PATH = re.compile(r"(\d{6,})")


class OzonMobileClient:
    """Fetch SKU card + stocks via Ozon mobile composer JSON."""

    marketplace = ParserMarketplace.OZON

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OZON_COMPOSER_BASE,
        timeout_seconds: float = 20.0,
        proxy_pool: ProxyPool | None = None,
        transport: MobileJsonTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport or MobileJsonTransport(
            marketplace=self.marketplace,
            proxy_pool=proxy_pool,
            timeout_seconds=timeout_seconds,
        )

    async def fetch_sku(self, request: ParseSkuRequest) -> ParsedSkuSnapshot:
        if request.marketplace is not ParserMarketplace.OZON:
            raise ParserSchemaError(
                "OzonMobileClient received non-Ozon request",
                marketplace=self.marketplace,
            )
        sku = _extract_ozon_sku(request.sku, request.product_url)
        page_url = _composer_page_path(sku, request.product_url)
        url = f"{self._base_url}/composer-api.bx/page/json/v2"
        params = {"url": page_url}
        payload = await self._transport.get_json(url, params=params)
        product = assert_ozon_product_payload(payload)
        return _map_ozon_product(
            product,
            sku=sku,
            product_url=request.product_url,
            raw_payload=payload,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()


def _extract_ozon_sku(sku: str, product_url: str | None) -> str:
    digits = "".join(ch for ch in sku if ch.isdigit())
    if digits:
        return digits
    if product_url:
        match = _SKU_IN_PATH.search(urlparse(product_url).path)
        if match:
            return match.group(1)
    raise ParserSchemaError(
        f"Cannot resolve Ozon SKU from sku={sku!r} url={product_url!r}",
        marketplace=ParserMarketplace.OZON,
        missing_keys=("sku",),
    )


def _composer_page_path(sku: str, product_url: str | None) -> str:
    if product_url:
        path = urlparse(product_url).path or ""
        if path.startswith("/product/"):
            return path if path.endswith("/") else f"{path}/"
    return f"/product/{sku}/"


def _map_ozon_product(
    product: dict[str, Any],
    *,
    sku: str,
    product_url: str | None,
    raw_payload: dict[str, Any],
) -> ParsedSkuSnapshot:
    title = str(product.get("title") or "").strip() or f"Ozon {sku}"
    price_raw = product.get("price")
    price_kopecks = _ozon_price_to_kopecks(price_raw)
    stocks = tuple(_normalize_ozon_stocks(product.get("stocks")))
    return ParsedSkuSnapshot(
        marketplace=ParserMarketplace.OZON,
        sku=sku,
        product_url=product_url,
        title=title[:500],
        price_kopecks=price_kopecks,
        price_before_discount_kopecks=None,
        currency="RUB",
        stocks=stocks,
        raw_payload=raw_payload,
    )


def _ozon_price_to_kopecks(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        # Ozon sometimes returns rubles as int; treat small ints as rubles.
        return value * 100 if value < 1_000_000 else value
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, str):
        digits = re.sub(r"[^\d.,]", "", value).replace(",", ".")
        if not digits:
            return 0
        try:
            return int(round(float(digits) * 100))
        except ValueError:
            return 0
    if isinstance(value, dict):
        for key in ("cardPrice", "price", "totalPrice", "value"):
            if key in value:
                return _ozon_price_to_kopecks(value[key])
    return 0


def _normalize_ozon_stocks(value: object) -> list[StockLevel]:
    if isinstance(value, int):
        return [
            StockLevel(warehouse_id="aggregate", quantity=max(0, value), warehouse_name=None)
        ]
    if isinstance(value, list):
        levels: list[StockLevel] = []
        for index, item in enumerate(value):
            if isinstance(item, int):
                levels.append(
                    StockLevel(
                        warehouse_id=f"wh-{index}",
                        quantity=max(0, item),
                        warehouse_name=None,
                    )
                )
            elif isinstance(item, dict):
                qty = item.get("qty", item.get("quantity", item.get("stock", 0)))
                wh = item.get("warehouse_id", item.get("wh", item.get("id", index)))
                name = item.get("name") or item.get("warehouse_name")
                try:
                    quantity = max(0, int(qty))
                except (TypeError, ValueError):
                    quantity = 0
                levels.append(
                    StockLevel(
                        warehouse_id=str(wh),
                        quantity=quantity,
                        warehouse_name=str(name)[:255] if name else None,
                    )
                )
        return levels
    if isinstance(value, dict):
        # Mapping warehouse_id → qty
        levels = []
        for key, qty in value.items():
            try:
                quantity = max(0, int(qty))
            except (TypeError, ValueError):
                continue
            levels.append(
                StockLevel(warehouse_id=str(key), quantity=quantity, warehouse_name=None)
            )
        return levels
    return []
