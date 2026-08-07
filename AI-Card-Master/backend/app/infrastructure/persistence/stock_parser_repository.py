"""SQLAlchemy persistence for stock-parser health + raw SKU / snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stock_parser import (
    ParserErrorKind,
    ParserHealthStatus,
    ParserHealthView,
    ParserMarketplace,
    STOCK_SNAPSHOT_UPSERT_BATCH_SIZE,
    SkuItemView,
    StockSnapshotView,
    StockSnapshotWrite,
)
from app.infrastructure.persistence.batching import chunk_rows
from app.models.stock_parser import ParserHealth, SkuItem, StockSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _health_view(row: ParserHealth) -> ParserHealthView:
    return ParserHealthView(
        id=row.id,
        marketplace=ParserMarketplace(row.marketplace),
        status=ParserHealthStatus(row.status),
        consecutive_errors=row.consecutive_errors,
        last_error_kind=(
            ParserErrorKind(row.last_error_kind) if row.last_error_kind else None
        ),
        last_error_message=row.last_error_message,
        last_traceback=row.last_traceback,
        last_success_at=_as_utc(row.last_success_at),
        last_failure_at=_as_utc(row.last_failure_at),
        broken_at=_as_utc(row.broken_at),
        alert_sent_at=_as_utc(row.alert_sent_at),
        updated_at=_as_utc(row.updated_at) or _utc_now(),
        created_at=_as_utc(row.created_at) or _utc_now(),
    )


def _sku_view(row: SkuItem) -> SkuItemView:
    return SkuItemView(
        id=row.id,
        marketplace=ParserMarketplace(row.marketplace),
        article=row.article,
        product_url=row.product_url,
        title=row.title,
        is_active=bool(row.is_active),
        created_at=_as_utc(row.created_at) or _utc_now(),
        updated_at=_as_utc(row.updated_at) or _utc_now(),
    )


def _snapshot_view(row: StockSnapshot) -> StockSnapshotView:
    return StockSnapshotView(
        id=row.id,
        sku_id=row.sku_id,
        captured_at=_as_utc(row.captured_at) or _utc_now(),
        warehouse_id=row.warehouse_id,
        quantity=int(row.quantity),
        price_kopecks=int(row.price_kopecks),
        currency=row.currency,
        created_at=_as_utc(row.created_at) or _utc_now(),
    )


class StockParserRepository:
    """Implements StockParserPersistencePort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        existing = await self.get_health(marketplace=marketplace)
        if existing is not None:
            return existing
        row = ParserHealth(
            marketplace=marketplace.value,
            status=ParserHealthStatus.HEALTHY.value,
            consecutive_errors=0,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _health_view(row)

    async def get_health(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView | None:
        result = await self._session.execute(
            select(ParserHealth).where(ParserHealth.marketplace == marketplace.value)
        )
        row = result.scalar_one_or_none()
        return _health_view(row) if row is not None else None

    async def record_success(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        row = await self._require_row(marketplace)
        if row.status != ParserHealthStatus.DISABLED.value:
            row.status = ParserHealthStatus.HEALTHY.value
            row.broken_at = None
        row.consecutive_errors = 0
        row.last_success_at = _utc_now()
        row.updated_at = _utc_now()
        await self._session.commit()
        await self._session.refresh(row)
        return _health_view(row)

    async def record_failure(
        self,
        *,
        marketplace: ParserMarketplace,
        error_kind: ParserErrorKind,
        error_message: str,
        traceback_text: str,
        mark_broken: bool,
    ) -> ParserHealthView:
        row = await self._require_row(marketplace)
        now = _utc_now()
        row.consecutive_errors = int(row.consecutive_errors) + 1
        row.last_error_kind = error_kind.value
        row.last_error_message = error_message[:4000]
        row.last_traceback = traceback_text[:20000]
        row.last_failure_at = now
        row.updated_at = now
        if row.status != ParserHealthStatus.DISABLED.value:
            if mark_broken:
                row.status = ParserHealthStatus.BROKEN.value
                row.broken_at = now
            else:
                row.status = ParserHealthStatus.DEGRADED.value
        await self._session.commit()
        await self._session.refresh(row)
        return _health_view(row)

    async def mark_alert_sent(
        self, *, marketplace: ParserMarketplace
    ) -> ParserHealthView:
        row = await self._require_row(marketplace)
        row.alert_sent_at = _utc_now()
        row.updated_at = _utc_now()
        await self._session.commit()
        await self._session.refresh(row)
        return _health_view(row)

    async def set_status(
        self,
        *,
        marketplace: ParserMarketplace,
        status: ParserHealthStatus,
    ) -> ParserHealthView:
        row = await self._require_row(marketplace)
        row.status = status.value
        row.updated_at = _utc_now()
        if status is ParserHealthStatus.HEALTHY:
            row.consecutive_errors = 0
            row.broken_at = None
        elif status is ParserHealthStatus.BROKEN and row.broken_at is None:
            row.broken_at = _utc_now()
        await self._session.commit()
        await self._session.refresh(row)
        return _health_view(row)

    async def upsert_sku_item(
        self,
        *,
        marketplace: ParserMarketplace,
        article: str,
        product_url: str,
        title: str | None = None,
        is_active: bool = True,
    ) -> SkuItemView:
        normalized_article = article.strip()
        result = await self._session.execute(
            select(SkuItem).where(
                SkuItem.marketplace == marketplace.value,
                SkuItem.article == normalized_article,
            )
        )
        row = result.scalar_one_or_none()
        now = _utc_now()
        if row is None:
            row = SkuItem(
                marketplace=marketplace.value,
                article=normalized_article,
                product_url=product_url[:1024],
                title=(title[:500] if title else None),
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.product_url = product_url[:1024]
            if title is not None:
                row.title = title[:500]
            row.is_active = is_active
            row.updated_at = now
        await self._session.commit()
        await self._session.refresh(row)
        return _sku_view(row)

    async def get_sku_item(
        self, *, marketplace: ParserMarketplace, article: str
    ) -> SkuItemView | None:
        result = await self._session.execute(
            select(SkuItem).where(
                SkuItem.marketplace == marketplace.value,
                SkuItem.article == article.strip(),
            )
        )
        row = result.scalar_one_or_none()
        return _sku_view(row) if row is not None else None

    async def list_active_sku_items(
        self,
        *,
        marketplace: ParserMarketplace | None = None,
        after_id: UUID | None = None,
        limit: int = 500,
    ) -> list[SkuItemView]:
        """Keyset page of active SKUs ordered by id (``id > after_id``)."""

        page_size = max(1, min(int(limit), 500))
        stmt = select(SkuItem).where(SkuItem.is_active.is_(True))
        if marketplace is not None:
            stmt = stmt.where(SkuItem.marketplace == marketplace.value)
        if after_id is not None:
            stmt = stmt.where(SkuItem.id > after_id)
        stmt = stmt.order_by(SkuItem.id).limit(page_size)
        result = await self._session.execute(stmt)
        return [_sku_view(row) for row in result.scalars().all()]

    async def ensure_stock_snapshot_partition(
        self, *, captured_at: datetime
    ) -> str:
        ts = _as_utc(captured_at) or _utc_now()
        result = await self._session.execute(
            text("SELECT ensure_stock_snapshot_month_partition(:ts)"),
            {"ts": ts},
        )
        name = result.scalar_one()
        await self._session.commit()
        return str(name)

    async def insert_stock_snapshots(
        self, *, rows: Sequence[StockSnapshotWrite]
    ) -> list[StockSnapshotView]:
        """Upsert snapshots in batches; retries must not create duplicate fact rows."""

        if not rows:
            return []

        # Ensure every month bucket exists before INSERT (DEFAULT is fallback).
        months_seen: set[tuple[int, int]] = set()
        prepared: list[dict[str, Any]] = []
        now = _utc_now()
        for item in rows:
            captured_at = _as_utc(item.captured_at) or now
            key = (captured_at.year, captured_at.month)
            if key not in months_seen:
                months_seen.add(key)
                await self.ensure_stock_snapshot_partition(captured_at=captured_at)
            prepared.append(
                {
                    "id": uuid4(),
                    "sku_id": item.sku_id,
                    "captured_at": captured_at,
                    "warehouse_id": item.warehouse_id,
                    "quantity": item.quantity,
                    "price_kopecks": item.price_kopecks,
                    "currency": item.currency,
                    "created_at": now,
                }
            )

        views: list[StockSnapshotView] = []
        for batch in chunk_rows(prepared, STOCK_SNAPSHOT_UPSERT_BATCH_SIZE):
            insert_stmt = pg_insert(StockSnapshot).values(batch)
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["sku_id", "warehouse_id", "captured_at"],
                set_={
                    "quantity": insert_stmt.excluded.quantity,
                    "price_kopecks": insert_stmt.excluded.price_kopecks,
                    "currency": insert_stmt.excluded.currency,
                },
            ).returning(StockSnapshot)
            result = await self._session.execute(stmt)
            views.extend(_snapshot_view(entity) for entity in result.scalars().all())
        await self._session.commit()
        return views

    async def list_stock_snapshots(
        self,
        *,
        sku_id: UUID,
        captured_from: datetime | None = None,
        captured_to: datetime | None = None,
        limit: int = 500,
    ) -> list[StockSnapshotView]:
        stmt = select(StockSnapshot).where(StockSnapshot.sku_id == sku_id)
        if captured_from is not None:
            stmt = stmt.where(
                StockSnapshot.captured_at >= (_as_utc(captured_from) or captured_from)
            )
        if captured_to is not None:
            stmt = stmt.where(
                StockSnapshot.captured_at < (_as_utc(captured_to) or captured_to)
            )
        stmt = stmt.order_by(StockSnapshot.captured_at.desc()).limit(max(1, min(limit, 5000)))
        result = await self._session.execute(stmt)
        return [_snapshot_view(row) for row in result.scalars().all()]

    async def _require_row(self, marketplace: ParserMarketplace) -> ParserHealth:
        result = await self._session.execute(
            select(ParserHealth).where(ParserHealth.marketplace == marketplace.value)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self.get_or_create_health(marketplace=marketplace)
            result = await self._session.execute(
                select(ParserHealth).where(
                    ParserHealth.marketplace == marketplace.value
                )
            )
            row = result.scalar_one()
        return row
