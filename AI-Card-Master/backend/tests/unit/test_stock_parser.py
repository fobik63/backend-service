"""Unit tests for isolated WB/Ozon stock-parser micro-module (plan §72)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.stock_parser_service import StockParserService
from app.domain.stock_parser import (
    CIRCUIT_BREAKER_THRESHOLD,
    ParseSkuRequest,
    ParsedSkuSnapshot,
    ParserErrorKind,
    ParserHealthStatus,
    ParserHealthView,
    ParserMarketplace,
    StockLevel,
    normalize_marketplace,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
)
from app.infrastructure.stock_parser.json_schema_guard import (
    assert_ozon_product_payload,
    assert_wildberries_card_payload,
)
from app.infrastructure.stock_parser.mobile_headers import mobile_headers
from app.infrastructure.stock_parser.proxy_pool import ProxyPool
from app.infrastructure.stock_parser.wildberries_mobile_client import (
    _map_wb_product,
)


def test_normalize_marketplace_aliases() -> None:
    assert normalize_marketplace("WB") is ParserMarketplace.WILDBERRIES
    assert normalize_marketplace("Озон") is ParserMarketplace.OZON


def test_proxy_pool_round_robin() -> None:
    pool = ProxyPool.from_csv("http://a:1, http://b:2;socks5://c:3")
    assert pool.size == 3
    urls = [pool.next().url for _ in range(4)]  # type: ignore[union-attr]
    assert urls[0] == "http://a:1"
    assert urls[1] == "http://b:2"
    assert urls[2] == "socks5://c:3"
    assert urls[3] == "http://a:1"


def test_proxy_pool_empty_is_direct() -> None:
    pool = ProxyPool.from_csv("")
    assert pool.enabled is False
    assert pool.next() is None


def test_mobile_headers_emulate_apps() -> None:
    wb = mobile_headers(marketplace="wildberries")
    assert "User-Agent" in wb
    assert "Accept" in wb
    ozon = mobile_headers(marketplace="ozon")
    assert "x-o3-app-name" in ozon or "User-Agent" in ozon
    assert "ozon" in ozon["User-Agent"].casefold() or "x-o3-app-name" in ozon


def test_wb_schema_guard_requires_stocks() -> None:
    payload = {
        "data": {
            "products": [
                {
                    "id": 123,
                    "name": "Chair",
                    "salePriceU": 10000,
                    "priceU": 12000,
                    "sizes": [{"stocks": [{"wh": 1, "qty": 5}]}],
                }
            ]
        }
    }
    product = assert_wildberries_card_payload(payload)
    assert product["id"] == 123


def test_wb_schema_guard_trips_when_stocks_missing() -> None:
    payload = {
        "data": {
            "products": [
                {
                    "id": 123,
                    "name": "Chair",
                    "salePriceU": 10000,
                    "priceU": 12000,
                    "sizes": [{"price": 1}],
                }
            ]
        }
    }
    with pytest.raises(ParserSchemaError) as exc_info:
        assert_wildberries_card_payload(payload)
    assert "stocks" in exc_info.value.missing_keys


def test_ozon_schema_guard_requires_stocks() -> None:
    product = assert_ozon_product_payload(
        {"id": "999", "title": "Lamp", "price": 499, "stocks": 12}
    )
    assert product["stocks"] == 12


def test_ozon_schema_guard_trips_on_drift() -> None:
    with pytest.raises(ParserSchemaError):
        assert_ozon_product_payload({"id": "1", "title": "X", "price": 10})


def test_map_wb_product_aggregates_stocks() -> None:
    product = {
        "id": 1,
        "name": "Test",
        "salePriceU": 15000,
        "priceU": 20000,
        "sizes": [
            {"stocks": [{"wh": 507, "qty": 3}, {"wh": 120762, "qty": 7}]},
            {"stocks": [{"wh": 507, "qty": 1}]},
        ],
    }
    snap = _map_wb_product(product, sku="1", product_url=None, raw_payload={})
    assert snap.total_stock == 11
    assert snap.price_kopecks == 15000


class _FakeHealthRepo:
    def __init__(self) -> None:
        self.rows: dict[ParserMarketplace, ParserHealthView] = {}

    def _blank(self, marketplace: ParserMarketplace) -> ParserHealthView:
        now = datetime.now(UTC)
        return ParserHealthView(
            id=uuid4(),
            marketplace=marketplace,
            status=ParserHealthStatus.HEALTHY,
            consecutive_errors=0,
            last_error_kind=None,
            last_error_message=None,
            last_traceback=None,
            last_success_at=None,
            last_failure_at=None,
            broken_at=None,
            alert_sent_at=None,
            updated_at=now,
            created_at=now,
        )

    async def get_or_create_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        if marketplace not in self.rows:
            self.rows[marketplace] = self._blank(marketplace)
        return self.rows[marketplace]

    async def get_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView | None:
        return self.rows.get(marketplace)

    async def record_success(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        row = await self.get_or_create_health(marketplace=marketplace)
        updated = row.model_copy(
            update={
                "status": ParserHealthStatus.HEALTHY,
                "consecutive_errors": 0,
                "last_success_at": datetime.now(UTC),
                "broken_at": None,
                "updated_at": datetime.now(UTC),
            }
        )
        self.rows[marketplace] = updated
        return updated

    async def record_failure(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        mark_broken: bool,
    ) -> ParserHealthView:
        row = await self.get_or_create_health(marketplace=marketplace)
        now = datetime.now(UTC)
        updated = row.model_copy(
            update={
                "consecutive_errors": row.consecutive_errors + 1,
                "last_error_kind": error_kind,
                "last_error_message": error_message,
                "last_traceback": traceback_text,
                "last_failure_at": now,
                "status": (
                    ParserHealthStatus.BROKEN
                    if mark_broken
                    else ParserHealthStatus.DEGRADED
                ),
                "broken_at": now if mark_broken else row.broken_at,
                "updated_at": now,
            }
        )
        self.rows[marketplace] = updated
        return updated

    async def mark_alert_sent(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        row = self.rows[marketplace]
        updated = row.model_copy(update={"alert_sent_at": datetime.now(UTC)})
        self.rows[marketplace] = updated
        return updated

    async def set_status(
        self,
        *,
        marketplace: ParserMarketplace,
        status: ParserHealthStatus,
    ) -> ParserHealthView:
        row = await self.get_or_create_health(marketplace=marketplace)
        updated = row.model_copy(
            update={
                "status": status,
                "consecutive_errors": 0
                if status is ParserHealthStatus.HEALTHY
                else row.consecutive_errors,
                "broken_at": None
                if status is ParserHealthStatus.HEALTHY
                else row.broken_at,
            }
        )
        self.rows[marketplace] = updated
        return updated


class _FailingParser:
    marketplace = ParserMarketplace.WILDBERRIES

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def fetch_sku(self, request: ParseSkuRequest) -> ParsedSkuSnapshot:
        raise self._exc

    async def aclose(self) -> None:
        return None


class _OkParser:
    marketplace = ParserMarketplace.WILDBERRIES

    async def fetch_sku(self, request: ParseSkuRequest) -> ParsedSkuSnapshot:
        return ParsedSkuSnapshot(
            marketplace=ParserMarketplace.WILDBERRIES,
            sku=request.sku,
            title="OK",
            price_kopecks=1000,
            stocks=(StockLevel(warehouse_id="1", quantity=2),),
        )

    async def aclose(self) -> None:
        return None


class _AlertRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_broken_alert(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        consecutive_errors: int,
        health_id: UUID,
    ) -> bool:
        self.calls.append(
            {
                "marketplace": marketplace,
                "error_kind": error_kind,
                "error_message": error_message,
                "traceback_text": traceback_text,
                "consecutive_errors": consecutive_errors,
                "health_id": health_id,
            }
        )
        return True


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_five_http_errors() -> None:
    repo = _FakeHealthRepo()
    alerts = _AlertRecorder()
    service = StockParserService(
        repo,
        {
            ParserMarketplace.WILDBERRIES: _FailingParser(
                ParserHttpError(
                    "forbidden",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    status_code=403,
                    kind=ParserErrorKind.HTTP_403,
                )
            )
        },
        alerts=alerts,
        circuit_breaker_threshold=CIRCUIT_BREAKER_THRESHOLD,
    )
    request = ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="111")

    for _ in range(4):
        result = await service.parse_sku(request)
        assert result.ok is False
        assert result.parser_stopped is False
        assert result.health_status is ParserHealthStatus.DEGRADED

    fifth = await service.parse_sku(request)
    assert fifth.parser_stopped is True
    assert fifth.health_status is ParserHealthStatus.BROKEN
    assert len(alerts.calls) == 1
    assert "Traceback" in alerts.calls[0]["traceback_text"] or alerts.calls[0][
        "traceback_text"
    ]

    refused = await service.parse_sku(request)
    assert refused.parser_stopped is True
    assert refused.ok is False
    assert len(alerts.calls) == 1  # no spam


@pytest.mark.asyncio
async def test_schema_drift_breaks_immediately_and_alerts() -> None:
    repo = _FakeHealthRepo()
    alerts = _AlertRecorder()
    service = StockParserService(
        repo,
        {
            ParserMarketplace.WILDBERRIES: _FailingParser(
                ParserSchemaError(
                    "missing stocks",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    missing_keys=("stocks",),
                    kind=ParserErrorKind.SCHEMA_DRIFT,
                )
            )
        },
        alerts=alerts,
    )
    result = await service.parse_sku(
        ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="222")
    )
    assert result.parser_stopped is True
    assert result.health_status is ParserHealthStatus.BROKEN
    assert result.error_kind is ParserErrorKind.SCHEMA_DRIFT
    assert len(alerts.calls) == 1


@pytest.mark.asyncio
async def test_success_resets_consecutive_errors() -> None:
    repo = _FakeHealthRepo()
    failing = _FailingParser(
        ParserHttpError(
            "not found",
            marketplace=ParserMarketplace.WILDBERRIES,
            status_code=404,
            kind=ParserErrorKind.HTTP_404,
        )
    )
    service = StockParserService(
        repo,
        {ParserMarketplace.WILDBERRIES: failing},
        alerts=_AlertRecorder(),
    )
    request = ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="333")
    await service.parse_sku(request)
    await service.parse_sku(request)
    assert repo.rows[ParserMarketplace.WILDBERRIES].consecutive_errors == 2

    service = StockParserService(
        repo,
        {ParserMarketplace.WILDBERRIES: _OkParser()},
        alerts=_AlertRecorder(),
    )
    ok = await service.parse_sku(request)
    assert ok.ok is True
    assert repo.rows[ParserMarketplace.WILDBERRIES].consecutive_errors == 0
    assert repo.rows[ParserMarketplace.WILDBERRIES].status is ParserHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_parse_many_stops_marketplace_after_break() -> None:
    repo = _FakeHealthRepo()
    alerts = _AlertRecorder()
    service = StockParserService(
        repo,
        {
            ParserMarketplace.WILDBERRIES: _FailingParser(
                ParserSchemaError(
                    "gone",
                    marketplace=ParserMarketplace.WILDBERRIES,
                    missing_keys=("stocks",),
                )
            )
        },
        alerts=alerts,
    )
    results = await service.parse_many(
        [
            ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="1"),
            ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="2"),
            ParseSkuRequest(marketplace=ParserMarketplace.WILDBERRIES, sku="3"),
        ]
    )
    assert results[0].parser_stopped is True
    assert results[1].parser_stopped is True
    assert "Skipped" in (results[1].error_message or "")
    assert len(alerts.calls) == 1
