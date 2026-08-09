"""SQLAlchemy persistence for Enterprise Audit Log (plan §81)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit_log import (
    AuditArchiveResult,
    AuditEventRecord,
    AuditEventView,
    AuditSearchQuery,
    AuditSearchResult,
)
from app.domain.audit_log import (
    normalize_audit_event as _normalize,
)
from app.infrastructure.persistence.batching import (
    DEFAULT_UPSERT_BATCH_SIZE,
    chunk_rows,
)
from app.models.audit_log import AuditLog, AuditLogArchive

logger = logging.getLogger(__name__)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_view(row: AuditLog | AuditLogArchive, *, archived: bool) -> AuditEventView:
    return AuditEventView(
        event_id=row.id,
        user_id=row.user_id,
        event_type=row.event_type,
        status=row.status,
        ip=row.ip,
        visitor_id=row.visitor_id,
        telegram_id=row.telegram_id,
        user_agent=row.user_agent,
        endpoint=row.endpoint,
        http_method=row.http_method,
        request_id=row.request_id,
        duration_ms=row.duration_ms,
        actor_type=row.actor_type,
        message=row.message,
        metadata=row.event_metadata,
        created_at=_to_utc(row.created_at),
        archived=archived,
    )


class AuditLogRepository:
    """Writes audit events and supports indexed search + archival."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(self, event: AuditEventRecord, *, commit: bool = True) -> UUID:
        normalized = _normalize(event)
        created_at = _to_utc(normalized.created_at or datetime.now(UTC))
        event_id = normalized.event_id or uuid4()
        self._session.add(
            AuditLog(
                id=event_id,
                user_id=normalized.user_id,
                event_type=normalized.event_type.value,
                status=normalized.status.value,
                ip=normalized.ip,
                visitor_id=normalized.visitor_id,
                telegram_id=normalized.telegram_id,
                user_agent=normalized.user_agent,
                endpoint=normalized.endpoint,
                http_method=normalized.http_method,
                request_id=normalized.request_id,
                duration_ms=normalized.duration_ms,
                actor_type=normalized.actor_type,
                message=normalized.message,
                event_metadata=normalized.metadata,
                created_at=created_at,
            )
        )
        if commit:
            await self._session.commit()
        else:
            await self._session.flush()
        return event_id

    async def search(self, query: AuditSearchQuery) -> AuditSearchResult:
        active_items, active_total = await self._search_table(
            AuditLog,
            query,
            archived=False,
        )
        if not query.include_archived:
            return AuditSearchResult(
                items=tuple(active_items),
                total=active_total,
                limit=query.limit,
                offset=query.offset,
            )

        # Merge active + archive with unified offset/limit (active first by time desc).
        archived_items, archived_total = await self._search_table(
            AuditLogArchive,
            AuditSearchQuery(
                user_id=query.user_id,
                event_type=query.event_type,
                ip=query.ip,
                request_id=query.request_id,
                created_from=query.created_from,
                created_to=query.created_to,
                include_archived=False,
                limit=query.limit + query.offset,
                offset=0,
            ),
            archived=True,
        )
        merged = sorted(
            [*active_items, *archived_items],
            key=lambda item: item.created_at,
            reverse=True,
        )
        sliced = merged[query.offset : query.offset + query.limit]
        return AuditSearchResult(
            items=tuple(sliced),
            total=active_total + archived_total,
            limit=query.limit,
            offset=query.offset,
        )

    async def _search_table(
        self,
        model: type[AuditLog] | type[AuditLogArchive],
        query: AuditSearchQuery,
        *,
        archived: bool,
    ) -> tuple[list[AuditEventView], int]:
        filters = []
        if query.user_id is not None:
            filters.append(model.user_id == query.user_id)
        if query.event_type is not None:
            filters.append(model.event_type == query.event_type.value)
        if query.ip:
            filters.append(model.ip == query.ip)
        if query.request_id:
            filters.append(model.request_id == query.request_id)
        if query.created_from is not None:
            filters.append(model.created_at >= _to_utc(query.created_from))
        if query.created_to is not None:
            filters.append(model.created_at <= _to_utc(query.created_to))

        count_stmt: Select[tuple[int]] = select(func.count()).select_from(model)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)

        stmt: Select[tuple] = select(model)
        if filters:
            stmt = stmt.where(*filters)
        stmt = (
            stmt.order_by(model.created_at.desc())
            .offset(max(0, query.offset))
            .limit(max(1, min(query.limit, 500)))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_row_to_view(row, archived=archived) for row in rows], total

    async def archive_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int = 1000,
    ) -> AuditArchiveResult:
        """Copy a batch of old rows into archives, then delete from hot table."""

        cutoff_utc = _to_utc(cutoff)
        limit = max(1, min(batch_size, 5000))
        stmt = (
            select(AuditLog)
            .where(AuditLog.created_at < cutoff_utc)
            .order_by(AuditLog.created_at.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        if not rows:
            return AuditArchiveResult(archived_count=0, cutoff=cutoff_utc, batches=0)

        now = datetime.now(UTC)
        payloads: list[dict] = []
        ids: list[UUID] = []
        for row in rows:
            ids.append(row.id)
            payloads.append(
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "event_type": row.event_type,
                    "status": row.status,
                    "ip": row.ip,
                    "visitor_id": row.visitor_id,
                    "telegram_id": row.telegram_id,
                    "user_agent": row.user_agent,
                    "endpoint": row.endpoint,
                    "http_method": row.http_method,
                    "request_id": row.request_id,
                    "duration_ms": row.duration_ms,
                    "actor_type": row.actor_type,
                    "message": row.message,
                    "event_metadata": row.event_metadata,
                    "created_at": row.created_at,
                    "archived_at": now,
                }
            )

        upsert_batches = 0
        for batch in chunk_rows(payloads, DEFAULT_UPSERT_BATCH_SIZE):
            stmt = (
                pg_insert(AuditLogArchive)
                .values(batch)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await self._session.execute(stmt)
            upsert_batches += 1

        await self._session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
        await self._session.commit()
        return AuditArchiveResult(
            archived_count=len(ids),
            cutoff=cutoff_utc,
            batches=upsert_batches,
        )


class FailOpenAuditLogRepository:
    """Wraps repository so audit writes never break product flows."""

    def __init__(self, inner: AuditLogRepository) -> None:
        self._inner = inner

    async def record_event(self, event: AuditEventRecord, *, commit: bool = True) -> UUID:
        try:
            return await self._inner.record_event(event, commit=commit)
        except Exception:
            logger.warning("Failed to persist audit log event", exc_info=True)
            return event.event_id or uuid4()

    async def search(self, query: AuditSearchQuery) -> AuditSearchResult:
        return await self._inner.search(query)

    async def archive_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int = 1000,
    ) -> AuditArchiveResult:
        return await self._inner.archive_before(cutoff=cutoff, batch_size=batch_size)
