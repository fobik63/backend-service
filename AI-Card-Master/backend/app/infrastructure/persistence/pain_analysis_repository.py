"""SQLAlchemy adapter for pain-analysis job persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pain_analysis import PainAnalysisJobStatus, PainAnalysisJobView
from app.models.pain_analysis import PainAnalysisJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: PainAnalysisJob) -> PainAnalysisJobView:
    return PainAnalysisJobView(
        id=row.id,
        user_id=row.user_id,
        status=PainAnalysisJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        product_name=row.product_name,
        platform=row.platform,
        request_payload=dict(row.request_payload or {}),
        filter_preview=dict(row.filter_preview) if row.filter_preview else None,
        analysis_result=dict(row.analysis_result) if row.analysis_result else None,
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class PainAnalysisRepository:
    """Persist pain-analysis async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        product_name: str,
        platform: str,
        request_payload: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> PainAnalysisJobView:
        row = PainAnalysisJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=PainAnalysisJobStatus.QUEUED.value,
            model_name=model_name,
            product_name=product_name,
            platform=platform,
            request_payload=request_payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> PainAnalysisJobView | None:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(
                PainAnalysisJob.user_id == user_id,
                PainAnalysisJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> PainAnalysisJobView | None:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(
                PainAnalysisJob.id == job_id,
                PainAnalysisJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> PainAnalysisJobView | None:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(PainAnalysisJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: PainAnalysisJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> PainAnalysisJobView:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(PainAnalysisJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Pain analysis job not found: {job_id}")
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

    async def save_filter_preview(
        self,
        *,
        job_id: UUID,
        filter_preview: dict[str, Any],
    ) -> PainAnalysisJobView:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(PainAnalysisJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Pain analysis job not found: {job_id}")
        row.filter_preview = filter_preview
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_filter_checkpoint(
        self,
        *,
        job_id: UUID,
        filter_preview: dict[str, Any],
        next_status: PainAnalysisJobStatus,
    ) -> PainAnalysisJobView:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(PainAnalysisJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Pain analysis job not found: {job_id}")
        row.filter_preview = filter_preview
        row.status = next_status.value
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        analysis_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> PainAnalysisJobView:
        row = await self._session.scalar(
            select(PainAnalysisJob).where(PainAnalysisJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Pain analysis job not found: {job_id}")
        row.analysis_result = analysis_result
        row.input_tokens = int(row.input_tokens or 0) + max(input_tokens_delta, 0)
        row.output_tokens = int(row.output_tokens or 0) + max(output_tokens_delta, 0)
        row.status = PainAnalysisJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
