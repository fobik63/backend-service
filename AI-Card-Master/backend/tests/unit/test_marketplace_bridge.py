"""Unit tests for Marketplace Data Bridge aggregation and AES-256 crypto."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.application.marketplace_bridge_service import (
    MarketplaceBridgeNotFoundError,
    MarketplaceBridgeService,
)
from app.core.credential_crypto import decrypt_credentials, encrypt_credentials
from app.domain.export import MarketplaceCredentialView, MarketplacePlatform
from app.domain.marketplace_bridge import (
    BridgePlatform,
    MarketplaceDataPeriod,
    OrdersMetrics,
    PeriodWindow,
    PlatformDataSlice,
    SalesMetrics,
    StocksMetrics,
    build_aggregated_totals,
    empty_orders,
    empty_sales,
    empty_stocks,
    resolve_period_window,
)


def test_aes256_credential_roundtrip_uses_gcm_prefix() -> None:
    secret = "unit-test-marketplace-secret-aes256"
    payload = {"api_token": "wb-token-123"}
    token = encrypt_credentials(payload, secret=secret)
    assert token.startswith("aes256gcm.v1.")
    assert decrypt_credentials(token, secret=secret) == payload


def test_legacy_fernet_credentials_still_decrypt() -> None:
    secret = "legacy-fernet-secret"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    fernet = Fernet(base64.urlsafe_b64encode(digest))
    raw = json.dumps({"api_token": "old-token"}, sort_keys=True).encode("utf-8")
    legacy = fernet.encrypt(raw).decode("ascii")
    assert decrypt_credentials(legacy, secret=secret) == {"api_token": "old-token"}


def test_resolve_period_window_day_week_month() -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    day = resolve_period_window(MarketplaceDataPeriod.DAY, now=now)
    week = resolve_period_window(MarketplaceDataPeriod.WEEK, now=now)
    month = resolve_period_window(MarketplaceDataPeriod.MONTH, now=now)
    assert day.date_to == now
    assert day.date_from == now - timedelta(days=1)
    assert week.date_from == now - timedelta(days=7)
    assert month.date_from == now - timedelta(days=30)


def test_build_aggregated_totals_skips_errors_and_disconnected() -> None:
    platforms = (
        PlatformDataSlice(
            platform=BridgePlatform.WILDBERRIES,
            connected=True,
            sales=SalesMetrics(count=2, revenue=100.0),
            stocks=StocksMetrics(sku_count=3, total_quantity=10),
            orders=OrdersMetrics(count=4, cancelled_count=1),
        ),
        PlatformDataSlice(
            platform=BridgePlatform.OZON,
            connected=True,
            sales=empty_sales(),
            stocks=empty_stocks(),
            orders=empty_orders(),
            error="upstream timeout",
        ),
        PlatformDataSlice(
            platform=BridgePlatform.OZON,
            connected=False,
            sales=SalesMetrics(count=99, revenue=999.0),
            stocks=StocksMetrics(sku_count=1, total_quantity=1),
            orders=OrdersMetrics(count=1, cancelled_count=0),
        ),
    )
    totals = build_aggregated_totals(platforms)
    assert totals.connected_platforms == 2
    assert totals.sales.count == 2
    assert totals.sales.revenue == 100.0
    assert totals.stocks.total_quantity == 10
    assert totals.orders.cancelled_count == 1


class _FakeCredentials:
    def __init__(self, mapping: dict[tuple, str]) -> None:
        self._mapping = mapping
        self.batch_calls = 0
        self.single_calls = 0

    async def get_credentials_ciphertext(self, *, user_id, platform):
        self.single_calls += 1
        return self._mapping.get((user_id, platform))

    async def get_credentials_ciphertext_batch(self, *, user_id, platforms):
        self.batch_calls += 1
        return {
            platform: cipher
            for (uid, platform), cipher in self._mapping.items()
            if uid == user_id and platform in platforms
        }

    async def list_credentials(self, user_id):
        return tuple(
            MarketplaceCredentialView(
                platform=platform,
                is_configured=True,
                label=None,
                updated_at=datetime.now(UTC),
            )
            for (uid, platform), _ in self._mapping.items()
            if uid == user_id
        )


class _FakeAnalytics:
    def __init__(self, platform: BridgePlatform) -> None:
        self.platform = platform
        self.calls: list[str] = []

    async def fetch_sales(self, *, credentials, window):
        self.calls.append("sales")
        assert "api_token" in credentials or "api_key" in credentials
        assert isinstance(window, PeriodWindow)
        return SalesMetrics(count=5, revenue=1500.5)

    async def fetch_stocks(self, *, credentials):
        self.calls.append("stocks")
        return StocksMetrics(sku_count=8, total_quantity=42)

    async def fetch_orders(self, *, credentials, window):
        self.calls.append("orders")
        return OrdersMetrics(count=7, cancelled_count=2)


@pytest.mark.asyncio
async def test_dashboard_aggregates_connected_platforms() -> None:
    user_id = uuid4()
    secret = "bridge-unit-secret"
    wb_cipher = encrypt_credentials({"api_token": "wb"}, secret=secret)
    ozon_cipher = encrypt_credentials(
        {"client_id": "1", "api_key": "oz"},
        secret=secret,
    )
    wb = _FakeAnalytics(BridgePlatform.WILDBERRIES)
    ozon = _FakeAnalytics(BridgePlatform.OZON)
    credentials = _FakeCredentials(
        {
            (user_id, MarketplacePlatform.WILDBERRIES): wb_cipher,
            (user_id, MarketplacePlatform.OZON): ozon_cipher,
        }
    )
    service = MarketplaceBridgeService(
        credentials,
        {
            BridgePlatform.WILDBERRIES: wb,
            BridgePlatform.OZON: ozon,
        },
        encryption_secret=secret,
    )

    view = await service.get_dashboard(
        user_id=user_id,
        period=MarketplaceDataPeriod.WEEK,
    )

    assert view.period is MarketplaceDataPeriod.WEEK
    assert len(view.platforms) == 2
    assert all(item.connected and item.error is None for item in view.platforms)
    assert view.totals.connected_platforms == 2
    assert view.totals.sales.count == 10
    assert view.totals.sales.revenue == 3001.0
    assert view.totals.stocks.total_quantity == 84
    assert view.totals.orders.count == 14
    assert credentials.batch_calls == 1
    assert credentials.single_calls == 0
    assert set(wb.calls) == {"sales", "stocks", "orders"}
    assert set(ozon.calls) == {"sales", "stocks", "orders"}


@pytest.mark.asyncio
async def test_platform_metrics_requires_credentials() -> None:
    service = MarketplaceBridgeService(
        _FakeCredentials({}),
        {
            BridgePlatform.WILDBERRIES: _FakeAnalytics(BridgePlatform.WILDBERRIES),
        },
        encryption_secret="bridge-unit-secret",
    )
    with pytest.raises(MarketplaceBridgeNotFoundError):
        await service.get_platform_metrics(
            user_id=uuid4(),
            platform=BridgePlatform.WILDBERRIES,
            period=MarketplaceDataPeriod.DAY,
        )
