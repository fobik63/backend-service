"""SQLAlchemy adapter for AI Strategy job persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ai_strategy import StrategyJobStatus, StrategyJobView
from app.models.ai_strategy import AiStrategyJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: AiStrategyJob) -> StrategyJobView:
    return StrategyJobView(
        id=row.id,
        user_id=row.user_id,
        status=StrategyJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        niche_key=row.niche_key,
        marketplace=row.marketplace,
        user_card_payload=dict(row.user_card_payload or {}),
        leader_card_payload=dict(row.leader_card_payload or {}),
        compare_config=dict(row.compare_config or {}),
        compare_report=dict(row.compare_report) if row.compare_report else None,
        plan_result=dict(row.plan_result) if row.plan_result else None,
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class AiStrategyRepository:
    """Persist AI Strategy async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        user_card_payload: dict[str, Any],
        leader_card_payload: dict[str, Any],
        compare_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> StrategyJobView:
        row = AiStrategyJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=StrategyJobStatus.QUEUED.value,
            model_name=model_name,
            niche_key=niche_key,
            marketplace=marketplace,
            user_card_payload=user_card_payload,
            leader_card_payload=leader_card_payload,
            compare_config=compare_config,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> StrategyJobView | None:
        row = await self._session.scalar(
            select(AiStrategyJob).where(
                AiStrategyJob.user_id == user_id,
                AiStrategyJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> StrategyJobView | None:
        row = await self._session.scalar(
            select(AiStrategyJob).where(
                AiStrategyJob.id == job_id,
                AiStrategyJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> StrategyJobView | None:
        row = await self._session.scalar(
            select(AiStrategyJob).where(AiStrategyJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: StrategyJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> StrategyJobView:
        row = await self._session.scalar(
            select(AiStrategyJob).where(AiStrategyJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"AI Strategy job not found: {job_id}")
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

    async def save_compare_report(
        self,
        *,
        job_id: UUID,
        compare_report: dict[str, Any],
    ) -> StrategyJobView:
        row = await self._session.scalar(
            select(AiStrategyJob).where(AiStrategyJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"AI Strategy job not found: {job_id}")
        row.compare_report = compare_report
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        plan_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> StrategyJobView:
        row = await self._session.scalar(
            select(AiStrategyJob).where(AiStrategyJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"AI Strategy job not found: {job_id}")
        row.plan_result = plan_result
        row.input_tokens = int(row.input_tokens or 0) + max(input_tokens_delta, 0)
        row.output_tokens = int(row.output_tokens or 0) + max(output_tokens_delta, 0)
        row.status = StrategyJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
