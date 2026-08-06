"""SQLAlchemy persistence for stock-parser health / circuit-breaker state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stock_parser import (
    ParserErrorKind,
    ParserHealthStatus,
    ParserHealthView,
    ParserMarketplace,
)
from app.models.stock_parser import ParserHealth


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
