"""Unit tests for Enterprise Audit Log & Event Tracking (plan §81)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.api.audit_log_schemas import search_result_to_response
from app.application.audit_log_service import AuditLogService, NoopAuditEventExporter
from app.domain.audit_log import (
    AuditArchivePolicy,
    AuditArchiveResult,
    AuditEventRecord,
    AuditEventStatus,
    AuditEventType,
    AuditEventView,
    AuditSearchQuery,
    AuditSearchResult,
    audit_event_to_export_payload,
    normalize_audit_event,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.events: list[AuditEventRecord] = []
        self.archived_cutoff: datetime | None = None

    async def record_event(self, event: AuditEventRecord, *, commit: bool = True) -> UUID:
        _ = commit
        event_id = event.event_id or uuid4()
        self.events.append(event)
        return event_id

    async def search(self, query: AuditSearchQuery) -> AuditSearchResult:
        items = []
        for event in self.events:
            if query.user_id is not None and event.user_id != query.user_id:
                continue
            if query.event_type is not None and event.event_type != query.event_type:
                continue
            if query.ip and event.ip != query.ip:
                continue
            if query.request_id and event.request_id != query.request_id:
                continue
            items.append(
                AuditEventView(
                    event_id=event.event_id or uuid4(),
                    user_id=event.user_id,
                    event_type=event.event_type.value,
                    status=event.status.value,
                    ip=event.ip,
                    visitor_id=event.visitor_id,
                    telegram_id=event.telegram_id,
                    user_agent=event.user_agent,
                    endpoint=event.endpoint,
                    http_method=event.http_method,
                    request_id=event.request_id,
                    duration_ms=event.duration_ms,
                    actor_type=event.actor_type,
                    message=event.message,
                    metadata=event.metadata,
                    created_at=event.created_at or datetime.now(UTC),
                )
            )
        sliced = items[query.offset : query.offset + query.limit]
        return AuditSearchResult(
            items=tuple(sliced),
            total=len(items),
            limit=query.limit,
            offset=query.offset,
        )

    async def archive_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int = 1000,
    ) -> AuditArchiveResult:
        self.archived_cutoff = cutoff
        kept: list[AuditEventRecord] = []
        removed = 0
        for event in self.events:
            if (
                removed < batch_size
                and event.created_at is not None
                and event.created_at < cutoff
            ):
                removed += 1
                continue
            kept.append(event)
        self.events = kept
        return AuditArchiveResult(archived_count=removed, cutoff=cutoff, batches=1)


class _CountingExporter:
    def __init__(self) -> None:
        self.exported: list[tuple[UUID, AuditEventRecord]] = []

    async def export(self, event: AuditEventRecord, *, event_id: UUID) -> None:
        self.exported.append((event_id, event))


def test_normalize_audit_event_clips_fields() -> None:
    event = normalize_audit_event(
        AuditEventRecord(
            event_type=AuditEventType.USER_LOGIN,
            status=AuditEventStatus.SUCCESS,
            ip="  10.0.0.1  ",
            user_agent="x" * 600,
            http_method=" POST ",
            actor_type=" user ",
            message="m" * 3000,
        )
    )
    assert event.ip == "10.0.0.1"
    assert event.user_agent is not None and len(event.user_agent) == 512
    assert event.http_method == "POST"
    assert event.actor_type == "user"
    assert event.message is not None and len(event.message) == 2000


def test_export_payload_is_backend_agnostic() -> None:
    event_id = uuid4()
    event = AuditEventRecord(
        event_type=AuditEventType.PAYMENT_PURCHASED,
        status=AuditEventStatus.SUCCESS,
        user_id=uuid4(),
        request_id="req-1",
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    payload = audit_event_to_export_payload(event, event_id=event_id)
    assert payload["event_id"] == str(event_id)
    assert payload["event_type"] == "payment.purchased"
    assert payload["request_id"] == "req-1"
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_audit_log_service_records_and_exports() -> None:
    repo = _FakeRepo()
    exporter = _CountingExporter()
    service = AuditLogService(
        repository=repo,
        exporter=exporter,
        archive_policy=AuditArchivePolicy(retention_days=90, enabled=True),
        enabled=True,
    )
    user_id = uuid4()
    event_id = await service.record_event(
        AuditEventRecord(
            event_type=AuditEventType.GENERATION_STARTED,
            status=AuditEventStatus.SUCCESS,
            user_id=user_id,
            ip="1.2.3.4",
            request_id="abc",
            endpoint="/api/v1/generations",
            http_method="POST",
            duration_ms=120,
        )
    )
    assert event_id is not None
    assert len(repo.events) == 1
    assert len(exporter.exported) == 1
    assert exporter.exported[0][0] == event_id


@pytest.mark.asyncio
async def test_audit_log_service_disabled() -> None:
    repo = _FakeRepo()
    service = AuditLogService(
        repository=repo,
        exporter=NoopAuditEventExporter(),
        enabled=False,
    )
    result = await service.record_event(
        AuditEventRecord(event_type=AuditEventType.USER_LOGOUT)
    )
    assert result is None
    assert repo.events == []


@pytest.mark.asyncio
async def test_audit_log_service_search_filters() -> None:
    repo = _FakeRepo()
    service = AuditLogService(repository=repo, exporter=NoopAuditEventExporter())
    user_a = uuid4()
    user_b = uuid4()
    await service.record_event(
        AuditEventRecord(
            event_type=AuditEventType.USER_LOGIN,
            user_id=user_a,
            ip="10.0.0.1",
            request_id="r1",
        )
    )
    await service.record_event(
        AuditEventRecord(
            event_type=AuditEventType.PAYMENT_PURCHASED,
            user_id=user_b,
            ip="10.0.0.2",
            request_id="r2",
        )
    )
    by_user = await service.search_events(AuditSearchQuery(user_id=user_a, limit=50))
    assert by_user.total == 1
    assert by_user.items[0].event_type == "user.login"

    by_type = await service.search_events(
        AuditSearchQuery(event_type=AuditEventType.PAYMENT_PURCHASED)
    )
    assert by_type.total == 1

    by_ip = await service.search_events(AuditSearchQuery(ip="10.0.0.2"))
    assert by_ip.total == 1

    by_rid = await service.search_events(AuditSearchQuery(request_id="r1"))
    assert by_rid.total == 1

    response = search_result_to_response(by_user)
    assert response.total == 1
    assert response.items[0].request_id == "r1"


@pytest.mark.asyncio
async def test_audit_log_service_archive_policy() -> None:
    repo = _FakeRepo()
    old = datetime.now(UTC) - timedelta(days=120)
    fresh = datetime.now(UTC)
    repo.events = [
        AuditEventRecord(
            event_type=AuditEventType.SYSTEM_EVENT,
            created_at=old,
            event_id=uuid4(),
        ),
        AuditEventRecord(
            event_type=AuditEventType.SYSTEM_EVENT,
            created_at=fresh,
            event_id=uuid4(),
        ),
    ]
    service = AuditLogService(
        repository=repo,
        exporter=NoopAuditEventExporter(),
        archive_policy=AuditArchivePolicy(retention_days=90, batch_size=100, enabled=True),
    )
    result = await service.archive_old_events(now=fresh)
    assert result.archived_count >= 1
    assert repo.archived_cutoff is not None
    assert len(repo.events) == 1
