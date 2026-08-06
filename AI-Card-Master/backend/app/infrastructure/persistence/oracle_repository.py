"""SQLAlchemy adapter for Oracle prediction job persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.oracle import OracleJobStatus, OracleJobView
from app.models.oracle import OraclePredictionJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: OraclePredictionJob) -> OracleJobView:
    queries = row.queries_payload or []
    if not isinstance(queries, list):
        queries = []
    supply = row.supply_payload or []
    if not isinstance(supply, list):
        supply = []
    notifications = row.notifications
    if notifications is not None and not isinstance(notifications, list):
        notifications = []
    return OracleJobView(
        id=row.id,
        user_id=row.user_id,
        status=OracleJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        niche_key=row.niche_key,
        marketplace=row.marketplace,
        queries_payload=tuple(
            dict(item) for item in queries if isinstance(item, dict)
        ),
        supply_payload=tuple(
            dict(item) for item in supply if isinstance(item, dict)
        ),
        gap_config=dict(row.gap_config or {}),
        scan_report=dict(row.scan_report) if row.scan_report else None,
        prediction_result=(
            dict(row.prediction_result) if row.prediction_result else None
        ),
        notifications=(
            [str(item) for item in notifications if isinstance(item, str)]
            if notifications is not None
            else None
        ),
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class OracleRepository:
    """Persist Oracle prediction async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        queries_payload: list[dict[str, Any]],
        supply_payload: list[dict[str, Any]],
        gap_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> OracleJobView:
        row = OraclePredictionJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=OracleJobStatus.QUEUED.value,
            model_name=model_name,
            niche_key=niche_key,
            marketplace=marketplace,
            queries_payload=queries_payload,
            supply_payload=supply_payload,
            gap_config=gap_config,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> OracleJobView | None:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(
                OraclePredictionJob.user_id == user_id,
                OraclePredictionJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> OracleJobView | None:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(
                OraclePredictionJob.id == job_id,
                OraclePredictionJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> OracleJobView | None:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(OraclePredictionJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def list_recent_notifications(
        self, *, user_id: UUID, limit: int = 20
    ) -> list[OracleJobView]:
        result = await self._session.scalars(
            select(OraclePredictionJob)
            .where(
                OraclePredictionJob.user_id == user_id,
                OraclePredictionJob.status == OracleJobStatus.COMPLETED.value,
                OraclePredictionJob.notifications.is_not(None),
            )
            .order_by(OraclePredictionJob.completed_at.desc().nullslast())
            .limit(limit)
        )
        return [_job_view(row) for row in result.all()]

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: OracleJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> OracleJobView:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(OraclePredictionJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Oracle job not found: {job_id}")
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

    async def save_scan_report(
        self,
        *,
        job_id: UUID,
        scan_report: dict[str, Any],
    ) -> OracleJobView:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(OraclePredictionJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Oracle job not found: {job_id}")
        row.scan_report = scan_report
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        prediction_result: dict[str, Any],
        notifications: list[str],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> OracleJobView:
        row = await self._session.scalar(
            select(OraclePredictionJob).where(OraclePredictionJob.id == job_id)
        )
        if row is None:
            raise ValueError(f"Oracle job not found: {job_id}")
        row.prediction_result = prediction_result
        row.notifications = notifications
        row.input_tokens = int(row.input_tokens or 0) + max(input_tokens_delta, 0)
        row.output_tokens = int(row.output_tokens or 0) + max(output_tokens_delta, 0)
        row.status = OracleJobStatus.COMPLETED.value
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
