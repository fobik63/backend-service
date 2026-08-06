"""SQLAlchemy adapter for competitor-audit job persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.competitor_audit import (
    CompetitorAuditJobStatus,
    CompetitorAuditJobView,
)
from app.models.competitor_audit import CompetitorAuditJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: CompetitorAuditJob) -> CompetitorAuditJobView:
    links = row.links_payload or []
    return CompetitorAuditJobView(
        id=row.id,
        user_id=row.user_id,
        status=CompetitorAuditJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        links_payload=tuple(str(item) for item in links),
        result_payload=dict(row.result_payload) if row.result_payload else None,
        analysis_payload=dict(row.analysis_payload) if row.analysis_payload else None,
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=int(row.input_tokens or 0),
        output_tokens=int(row.output_tokens or 0),
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class CompetitorAuditRepository:
    """Persist competitor-audit async scrape + Claude analysis jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        links: list[str],
        idempotency_key: str | None = None,
    ) -> CompetitorAuditJobView:
        row = CompetitorAuditJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=CompetitorAuditJobStatus.QUEUED.value,
            links_payload=list(links),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> CompetitorAuditJobView | None:
        row = await self._session.scalar(
            select(CompetitorAuditJob).where(
                CompetitorAuditJob.user_id == user_id,
                CompetitorAuditJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> CompetitorAuditJobView | None:
        row = await self._session.scalar(
            select(CompetitorAuditJob).where(
                CompetitorAuditJob.id == job_id,
                CompetitorAuditJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> CompetitorAuditJobView | None:
        row = await self._session.scalar(
            select(CompetitorAuditJob).where(CompetitorAuditJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: CompetitorAuditJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> CompetitorAuditJobView:
        row = await self._session.scalar(
            select(CompetitorAuditJob).where(CompetitorAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Competitor audit job not found: {job_id}")
        row.status = status.value
        row.updated_at = datetime.now(UTC)
        if celery_task_id is not None:
            row.celery_task_id = celery_task_id
        if error_message is not None:
            row.error_message = error_message
        if completed_at is not None:
            row.completed_at = completed_at
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_scrape_result(
        self,
        *,
        job_id: UUID,
        result_payload: dict[str, Any],
    ) -> CompetitorAuditJobView:
        """Persist scrape payload and transition to ANALYZING for Claude."""

        row = await self._session.scalar(
            select(CompetitorAuditJob).where(CompetitorAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Competitor audit job not found: {job_id}")
        row.result_payload = result_payload
        row.status = CompetitorAuditJobStatus.ANALYZING.value
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_analysis_result(
        self,
        *,
        job_id: UUID,
        analysis_payload: dict[str, Any],
        model_name: str,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> CompetitorAuditJobView:
        row = await self._session.scalar(
            select(CompetitorAuditJob).where(CompetitorAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Competitor audit job not found: {job_id}")
        row.analysis_payload = analysis_payload
        row.model_name = model_name.strip()[:128] if model_name else row.model_name
        row.input_tokens = int(row.input_tokens or 0) + max(0, input_tokens_delta)
        row.output_tokens = int(row.output_tokens or 0) + max(0, output_tokens_delta)
        row.status = CompetitorAuditJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        result_payload: dict[str, Any],
    ) -> CompetitorAuditJobView:
        """Scrape-only completion (no Claude) — used when analysis is skipped."""

        row = await self._session.scalar(
            select(CompetitorAuditJob).where(CompetitorAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Competitor audit job not found: {job_id}")
        row.result_payload = result_payload
        row.status = CompetitorAuditJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
