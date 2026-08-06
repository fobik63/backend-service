"""SQLAlchemy adapter for Claude reasoning job persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.claude_reasoning import (
    ClaudeOutboxMessage,
    ClaudeReasoningJobStatus,
    ClaudeReasoningJobView,
)
from app.models.claude_reasoning import ClaudeReasoningJob, ClaudeReasoningOutbox


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: ClaudeReasoningJob) -> ClaudeReasoningJobView:
    keys = row.image_object_keys or []
    if not isinstance(keys, list):
        keys = []
    return ClaudeReasoningJobView(
        id=row.id,
        user_id=row.user_id,
        status=ClaudeReasoningJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        image_object_keys=tuple(str(item) for item in keys),
        text_context=dict(row.text_context or {}),
        vision_result=dict(row.vision_result) if row.vision_result else None,
        reasoning_result=dict(row.reasoning_result) if row.reasoning_result else None,
        final_result=dict(row.final_result) if row.final_result else None,
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class ClaudeReasoningRepository:
    """Persist Claude Vision / CoT async jobs and transactional outbox rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        user_id: UUID,
        image_object_keys: tuple[str, ...],
        text_context: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> ClaudeReasoningJobView:
        row = ClaudeReasoningJob(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=ClaudeReasoningJobStatus.QUEUED.value,
            model_name=model_name,
            image_object_keys=list(image_object_keys),
            text_context=text_context,
        )
        self._session.add(row)
        await self._session.flush()
        self._session.add(
            ClaudeReasoningOutbox(
                event_type="run_chain_of_thought",
                aggregate_id=row.id,
                deduplication_key=f"claude:run:{row.id}",
                payload={"job_id": str(row.id)},
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if idempotency_key:
                existing = await self.find_idempotent_job(
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return existing
            raise
        await self._session.refresh(row)
        return _job_view(row)

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ClaudeReasoningJobView | None:
        row = await self._session.scalar(
            select(ClaudeReasoningJob).where(
                ClaudeReasoningJob.user_id == user_id,
                ClaudeReasoningJob.idempotency_key == idempotency_key,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> ClaudeReasoningJobView | None:
        row = await self._session.scalar(
            select(ClaudeReasoningJob).where(
                ClaudeReasoningJob.id == job_id,
                ClaudeReasoningJob.user_id == user_id,
            )
        )
        return _job_view(row) if row is not None else None

    async def get_job(self, *, job_id: UUID) -> ClaudeReasoningJobView | None:
        row = await self._session.scalar(
            select(ClaudeReasoningJob).where(ClaudeReasoningJob.id == job_id)
        )
        return _job_view(row) if row is not None else None

    async def claim_job(
        self,
        *,
        job_id: UUID,
        stale_before: datetime,
    ) -> ClaudeReasoningJobView | None:
        row = await self._session.scalar(
            select(ClaudeReasoningJob)
            .where(ClaudeReasoningJob.id == job_id)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        status = ClaudeReasoningJobStatus(row.status)
        if status in (
            ClaudeReasoningJobStatus.COMPLETED,
            ClaudeReasoningJobStatus.FAILED,
        ):
            return None
        updated_at = _to_utc(row.updated_at)
        if status == ClaudeReasoningJobStatus.QUEUED:
            row.status = ClaudeReasoningJobStatus.VISION_RUNNING.value
        elif status in (
            ClaudeReasoningJobStatus.VISION_RUNNING,
            ClaudeReasoningJobStatus.REASONING_RUNNING,
        ):
            if updated_at > stale_before:
                return None
            if row.vision_result is None:
                row.status = ClaudeReasoningJobStatus.VISION_RUNNING.value
            else:
                row.status = ClaudeReasoningJobStatus.REASONING_RUNNING.value
        else:
            return None
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: ClaudeReasoningJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> ClaudeReasoningJobView:
        row = await self._require(job_id)
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

    async def save_vision_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        row = await self._require(job_id)
        row.vision_result = vision_result
        row.status = ClaudeReasoningJobStatus.REASONING_RUNNING.value
        row.input_tokens = max(0, row.input_tokens + max(0, input_tokens_delta))
        row.output_tokens = max(0, row.output_tokens + max(0, output_tokens_delta))
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        reasoning_result: dict[str, Any],
        final_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        row = await self._require(job_id)
        row.reasoning_result = reasoning_result
        row.final_result = final_result
        row.status = ClaudeReasoningJobStatus.COMPLETED.value
        row.input_tokens = max(0, row.input_tokens + max(0, input_tokens_delta))
        row.output_tokens = max(0, row.output_tokens + max(0, output_tokens_delta))
        row.updated_at = datetime.now(UTC)
        row.completed_at = datetime.now(UTC)
        row.error_message = None
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def claim_outbox(self, *, limit: int) -> tuple[ClaudeOutboxMessage, ...]:
        now = datetime.now(UTC)
        stale_lock = now - timedelta(minutes=5)
        result = await self._session.scalars(
            select(ClaudeReasoningOutbox)
            .where(
                ClaudeReasoningOutbox.available_at <= now,
                or_(
                    ClaudeReasoningOutbox.status == "pending",
                    (
                        (ClaudeReasoningOutbox.status == "publishing")
                        & (ClaudeReasoningOutbox.locked_at < stale_lock)
                    ),
                ),
            )
            .order_by(ClaudeReasoningOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = list(result)
        for message in messages:
            message.status = "publishing"
            message.locked_at = now
            message.attempts += 1
        await self._session.commit()
        return tuple(
            ClaudeOutboxMessage(
                id=message.id,
                event_type=message.event_type,
                aggregate_id=message.aggregate_id,
                payload=dict(message.payload or {}),
                attempts=message.attempts,
            )
            for message in messages
        )

    async def mark_outbox_published(self, message_id: UUID) -> None:
        message = await self._session.get(ClaudeReasoningOutbox, message_id)
        if message is None:
            return
        message.status = "published"
        message.processed_at = datetime.now(UTC)
        message.last_error = None
        await self._session.commit()

    async def mark_outbox_failed(self, message_id: UUID, error: str) -> None:
        message = await self._session.get(ClaudeReasoningOutbox, message_id)
        if message is None:
            return
        message.status = "failed" if message.attempts >= 20 else "pending"
        message.last_error = error[:2000]
        message.locked_at = None
        message.available_at = datetime.now(UTC) + timedelta(
            seconds=min(2 ** min(message.attempts, 8), 300)
        )
        await self._session.commit()

    async def list_recoverable_job_ids(
        self,
        *,
        queued_before: datetime,
        processing_before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        rows = await self._session.scalars(
            select(ClaudeReasoningJob.id)
            .where(
                or_(
                    (
                        (ClaudeReasoningJob.status == ClaudeReasoningJobStatus.QUEUED.value)
                        & (ClaudeReasoningJob.created_at <= queued_before)
                    ),
                    (
                        ClaudeReasoningJob.status.in_(
                            (
                                ClaudeReasoningJobStatus.VISION_RUNNING.value,
                                ClaudeReasoningJobStatus.REASONING_RUNNING.value,
                            )
                        )
                        & (ClaudeReasoningJob.updated_at <= processing_before)
                    ),
                )
            )
            .order_by(ClaudeReasoningJob.updated_at.asc())
            .limit(limit)
        )
        return tuple(rows.all())

    async def enqueue_recovery_outbox(self, *, job_id: UUID) -> None:
        """Ensure a stalled job has a pending outbox event for re-dispatch."""

        dedup = f"claude:recover:{job_id}:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
        existing = await self._session.scalar(
            select(ClaudeReasoningOutbox.id).where(
                ClaudeReasoningOutbox.deduplication_key == dedup
            )
        )
        if existing is not None:
            return
        self._session.add(
            ClaudeReasoningOutbox(
                event_type="run_chain_of_thought",
                aggregate_id=job_id,
                deduplication_key=dedup,
                payload={"job_id": str(job_id)},
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()

    async def _require(self, job_id: UUID) -> ClaudeReasoningJob:
        row = await self._session.scalar(
            select(ClaudeReasoningJob).where(ClaudeReasoningJob.id == job_id)
        )
        if row is None:
            raise LookupError(f"Claude reasoning job {job_id} not found.")
        return row
