"""SQLAlchemy persistence for AI cost events + daily rollups (plan §80)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.cost_analytics_service import normalize_cost_event
from app.domain.cost_analytics import (
    CostCallStatus,
    CostEventRecord,
    ExpensiveOperation,
    PeriodCostTotals,
    empty_period_totals,
    is_generation_operation,
    quantize_usd,
)
from app.models.api_cost_daily_rollup import ApiCostDailyRollup
from app.models.api_usage_cost import ApiUsageCost

logger = logging.getLogger(__name__)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CostAnalyticsRepository:
    """Writes events and maintains O(1) daily rollups for dashboard reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(self, event: CostEventRecord, *, commit: bool = True) -> None:
        """Stage cost event + rollup upsert; commit unless nested in another TX."""

        await self.stage_event(event)
        if commit:
            await self._session.commit()

    async def stage_event(self, event: CostEventRecord) -> None:
        normalized = normalize_cost_event(event)
        created_at = _to_utc(normalized.created_at or datetime.now(UTC))
        day = created_at.date()
        is_gen = (
            normalized.generation_job_id is not None
            or is_generation_operation(normalized.operation)
        )
        gen_inc = 1 if is_gen else 0
        gen_cost_inc = normalized.total_cost_usd if is_gen else Decimal("0")
        success_inc = 1 if normalized.status == CostCallStatus.SUCCESS else 0
        error_inc = 1 if normalized.status == CostCallStatus.ERROR else 0
        timeout_inc = 1 if normalized.status == CostCallStatus.TIMEOUT else 0
        duration = normalized.duration_ms
        duration_inc = int(duration) if duration is not None else 0
        duration_sample_inc = 1 if duration is not None else 0

        self._session.add(
            ApiUsageCost(
                user_id=normalized.user_id,
                generation_job_id=normalized.generation_job_id,
                provider=normalized.provider,
                model_name=normalized.model_name,
                operation=normalized.operation,
                units=normalized.units,
                unit_cost_usd=normalized.unit_cost_usd,
                total_cost_usd=normalized.total_cost_usd,
                input_tokens=normalized.input_tokens,
                output_tokens=normalized.output_tokens,
                status=normalized.status.value,
                duration_ms=normalized.duration_ms,
                task_id=normalized.task_id,
                usage_metadata=normalized.metadata,
                created_at=created_at,
            )
        )

        stmt = (
            pg_insert(ApiCostDailyRollup)
            .values(
                day=day,
                provider=normalized.provider,
                operation=normalized.operation,
                events_count=1,
                success_count=success_inc,
                error_count=error_inc,
                timeout_count=timeout_inc,
                generation_events_count=gen_inc,
                generation_cost_usd=gen_cost_inc,
                total_cost_usd=normalized.total_cost_usd,
                total_input_tokens=normalized.input_tokens,
                total_output_tokens=normalized.output_tokens,
                total_duration_ms=duration_inc,
                duration_samples=duration_sample_inc,
                updated_at=created_at,
            )
            .on_conflict_do_update(
                constraint="uq_api_cost_daily_rollups_day_provider_operation",
                set_={
                    "events_count": ApiCostDailyRollup.events_count + 1,
                    "success_count": ApiCostDailyRollup.success_count + success_inc,
                    "error_count": ApiCostDailyRollup.error_count + error_inc,
                    "timeout_count": ApiCostDailyRollup.timeout_count + timeout_inc,
                    "generation_events_count": (
                        ApiCostDailyRollup.generation_events_count + gen_inc
                    ),
                    "generation_cost_usd": (
                        ApiCostDailyRollup.generation_cost_usd + gen_cost_inc
                    ),
                    "total_cost_usd": (
                        ApiCostDailyRollup.total_cost_usd + normalized.total_cost_usd
                    ),
                    "total_input_tokens": (
                        ApiCostDailyRollup.total_input_tokens + normalized.input_tokens
                    ),
                    "total_output_tokens": (
                        ApiCostDailyRollup.total_output_tokens + normalized.output_tokens
                    ),
                    "total_duration_ms": (
                        ApiCostDailyRollup.total_duration_ms + duration_inc
                    ),
                    "duration_samples": (
                        ApiCostDailyRollup.duration_samples + duration_sample_inc
                    ),
                    "updated_at": created_at,
                },
            )
        )
        await self._session.execute(stmt)

    async def sum_rollups(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> PeriodCostTotals:
        if day_to < day_from:
            return empty_period_totals()

        stmt: Select[tuple] = select(
            func.coalesce(func.sum(ApiCostDailyRollup.total_cost_usd), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.events_count), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.success_count), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.error_count), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.timeout_count), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.generation_events_count), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.generation_cost_usd), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.total_input_tokens), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.total_output_tokens), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.total_duration_ms), 0),
            func.coalesce(func.sum(ApiCostDailyRollup.duration_samples), 0),
        ).where(
            ApiCostDailyRollup.day >= day_from,
            ApiCostDailyRollup.day <= day_to,
        )
        row = (await self._session.execute(stmt)).one()
        return PeriodCostTotals(
            cost_usd=quantize_usd(Decimal(str(row[0] or "0"))),
            events_count=int(row[1] or 0),
            success_count=int(row[2] or 0),
            error_count=int(row[3] or 0),
            timeout_count=int(row[4] or 0),
            generation_events_count=int(row[5] or 0),
            generation_cost_usd=quantize_usd(Decimal(str(row[6] or "0"))),
            total_input_tokens=int(row[7] or 0),
            total_output_tokens=int(row[8] or 0),
            total_duration_ms=int(row[9] or 0),
            duration_samples=int(row[10] or 0),
        )

    async def sum_rollups_by_provider(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> dict[str, tuple[Decimal, int]]:
        if day_to < day_from:
            return {}

        stmt = (
            select(
                ApiCostDailyRollup.provider,
                func.coalesce(func.sum(ApiCostDailyRollup.total_cost_usd), 0),
                func.coalesce(func.sum(ApiCostDailyRollup.events_count), 0),
            )
            .where(
                ApiCostDailyRollup.day >= day_from,
                ApiCostDailyRollup.day <= day_to,
            )
            .group_by(ApiCostDailyRollup.provider)
        )
        result: dict[str, tuple[Decimal, int]] = {}
        for provider, cost, count in (await self._session.execute(stmt)).all():
            result[str(provider)] = (
                quantize_usd(Decimal(str(cost or "0"))),
                int(count or 0),
            )
        return result

    async def list_most_expensive(
        self,
        *,
        since: datetime,
        limit: int = 10,
    ) -> list[ExpensiveOperation]:
        stmt = (
            select(ApiUsageCost)
            .where(ApiUsageCost.created_at >= _to_utc(since))
            .order_by(ApiUsageCost.total_cost_usd.desc(), ApiUsageCost.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        items: list[ExpensiveOperation] = []
        for row in rows:
            items.append(
                ExpensiveOperation(
                    id=str(row.id),
                    provider=row.provider,
                    operation=row.operation,
                    model_name=row.model_name,
                    total_cost_usd=quantize_usd(Decimal(str(row.total_cost_usd))),
                    input_tokens=int(row.input_tokens or 0),
                    output_tokens=int(row.output_tokens or 0),
                    duration_ms=row.duration_ms,
                    status=row.status,
                    task_id=str(row.task_id) if row.task_id else None,
                    user_id=str(row.user_id) if row.user_id else None,
                    created_at=_to_utc(row.created_at),
                )
            )
        return items


class FailOpenCostAnalyticsRepository:
    """Wraps repository so cost logging never breaks callers."""

    def __init__(self, inner: CostAnalyticsRepository) -> None:
        self._inner = inner

    async def record_event(self, event: CostEventRecord, *, commit: bool = True) -> None:
        try:
            await self._inner.record_event(event, commit=commit)
        except Exception:
            logger.warning("Failed to persist API usage cost event", exc_info=True)

    async def sum_rollups(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> PeriodCostTotals:
        return await self._inner.sum_rollups(day_from=day_from, day_to=day_to)

    async def sum_rollups_by_provider(
        self,
        *,
        day_from: date,
        day_to: date,
    ) -> dict[str, tuple[Decimal, int]]:
        return await self._inner.sum_rollups_by_provider(
            day_from=day_from,
            day_to=day_to,
        )

    async def list_most_expensive(
        self,
        *,
        since: datetime,
        limit: int = 10,
    ) -> list[ExpensiveOperation]:
        return await self._inner.list_most_expensive(since=since, limit=limit)
