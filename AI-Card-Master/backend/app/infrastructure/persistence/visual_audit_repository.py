"""SQLAlchemy adapter for visual-audit job persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.visual_audit import VisualAuditJobStatus, VisualAuditJobView
from app.models.visual_audit import VisualAuditJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: VisualAuditJob) -> VisualAuditJobView:
    cards = row.cards_payload or []
    if not isinstance(cards, list):
        cards = []
    dissections = row.vision_dissections
    if dissections is not None and not isinstance(dissections, list):
        dissections = []
    return VisualAuditJobView(
        id=row.id,
        user_id=row.user_id,
        status=VisualAuditJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        niche_key=row.niche_key,
        marketplace=row.marketplace,
        cards_payload=tuple(dict(item) for item in cards if isinstance(item, dict)),
        filter_config=dict(row.filter_config or {}),
        filter_report=dict(row.filter_report) if row.filter_report else None,
        vision_dissections=(
            [dict(item) for item in dissections if isinstance(item, dict)]
            if dissections is not None
            else None
        ),
        generator_config=dict(row.generator_config) if row.generator_config else None,
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class VisualAuditRepository:
    """Persist niche visual-audit async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        cards_payload: list[dict[str, Any]],
        filter_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> VisualAuditJobView:
        row = VisualAuditJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=VisualAuditJobStatus.QUEUED.value,
            model_name=model_name,
            niche_key=niche_key,
            marketplace=marketplace,
            cards_payload=cards_payload,
            filter_config=filter_config,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VisualAuditJobView | None:
        row = await self._session.scalar(
            select(VisualAuditJob).where(
                VisualAuditJob.user_id == user_id,
                VisualAuditJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> VisualAuditJobView | None:
        row = await self._session.scalar(
            select(VisualAuditJob).where(
                VisualAuditJob.id == job_id,
                VisualAuditJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> VisualAuditJobView | None:
        row = await self._session.scalar(
            select(VisualAuditJob).where(VisualAuditJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: VisualAuditJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> VisualAuditJobView:
        row = await self._session.scalar(
            select(VisualAuditJob).where(VisualAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Visual audit job not found: {job_id}")
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

    async def save_filter_report(
        self,
        *,
        job_id: UUID,
        filter_report: dict[str, Any],
    ) -> VisualAuditJobView:
        row = await self._session.scalar(
            select(VisualAuditJob).where(VisualAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Visual audit job not found: {job_id}")
        row.filter_report = filter_report
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_filter_checkpoint(
        self,
        *,
        job_id: UUID,
        filter_report: dict[str, Any],
        next_status: VisualAuditJobStatus,
    ) -> VisualAuditJobView:
        row = await self._session.scalar(
            select(VisualAuditJob).where(VisualAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Visual audit job not found: {job_id}")
        row.filter_report = filter_report
        row.status = next_status.value
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        vision_dissections: list[dict[str, Any]],
        generator_config: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> VisualAuditJobView:
        row = await self._session.scalar(
            select(VisualAuditJob).where(VisualAuditJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Visual audit job not found: {job_id}")
        row.vision_dissections = vision_dissections
        row.generator_config = generator_config
        row.input_tokens = int(row.input_tokens or 0) + max(input_tokens_delta, 0)
        row.output_tokens = int(row.output_tokens or 0) + max(output_tokens_delta, 0)
        row.status = VisualAuditJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
