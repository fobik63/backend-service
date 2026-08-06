"""SQLAlchemy adapter for Eye-of-God (money-confirmed trigger) jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.eye_of_god import (
    EyeOfGodJobStatus,
    EyeOfGodJobView,
    SalesSpikeSignal,
)
from app.models.eye_of_god import EyeOfGodJob


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_view(row: EyeOfGodJob) -> EyeOfGodJobView:
    urls = row.image_urls or []
    if not isinstance(urls, list):
        urls = []
    return EyeOfGodJobView(
        id=row.id,
        status=EyeOfGodJobStatus(row.status),
        celery_task_id=row.celery_task_id,
        sku_id=row.sku_id,
        marketplace=row.marketplace,
        article=row.article,
        title=row.title,
        product_url=row.product_url,
        spike_payload=dict(row.spike_payload or {}),
        image_urls=tuple(str(item) for item in urls if item),
        vision_result=dict(row.vision_result) if row.vision_result else None,
        money_trigger_config=(
            dict(row.money_trigger_config) if row.money_trigger_config else None
        ),
        model_name=row.model_name,
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
    )


class EyeOfGodRepository:
    """Persist parser → Eye of God async jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        spike: SalesSpikeSignal,
        model_name: str,
        idempotency_key: str | None = None,
    ) -> EyeOfGodJobView:
        row = EyeOfGodJob(
            sku_id=spike.sku_id,
            idempotency_key=idempotency_key,
            status=EyeOfGodJobStatus.QUEUED.value,
            model_name=model_name,
            marketplace=spike.marketplace.value,
            article=spike.article,
            title=spike.title,
            product_url=spike.product_url,
            spike_payload=spike.model_dump(mode="json"),
            image_urls=list(spike.image_urls),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)

    async def find_recent_job_for_sku(
        self,
        *,
        sku_id: UUID,
        since: datetime,
    ) -> EyeOfGodJobView | None:
        stmt = (
            select(EyeOfGodJob)
            .where(
                EyeOfGodJob.sku_id == sku_id,
                EyeOfGodJob.created_at >= since,
                EyeOfGodJob.status.in_(
                    [
                        EyeOfGodJobStatus.QUEUED.value,
                        EyeOfGodJobStatus.FETCHING_IMAGE.value,
                        EyeOfGodJobStatus.VISION_RUNNING.value,
                        EyeOfGodJobStatus.COMPLETED.value,
                    ]
                ),
            )
            .order_by(EyeOfGodJob.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _job_view(row) if row else None

    async def find_idempotent_job(
        self, *, idempotency_key: str
    ) -> EyeOfGodJobView | None:
        stmt = select(EyeOfGodJob).where(
            EyeOfGodJob.idempotency_key == idempotency_key
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _job_view(row) if row else None

    async def get_job(self, *, job_id: UUID) -> EyeOfGodJobView | None:
        row = await self._session.get(EyeOfGodJob, job_id)
        return _job_view(row) if row else None

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: EyeOfGodJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> EyeOfGodJobView:
        row = await self._session.get(EyeOfGodJob, job_id)
        if row is None:
            raise LookupError(f"EyeOfGodJob {job_id} not found")
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

    async def save_money_trigger_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict[str, Any],
        money_trigger_config: dict[str, Any],
        image_urls: list[str] | None = None,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> EyeOfGodJobView:
        row = await self._session.get(EyeOfGodJob, job_id)
        if row is None:
            raise LookupError(f"EyeOfGodJob {job_id} not found")
        now = datetime.now(UTC)
        row.vision_result = vision_result
        row.money_trigger_config = money_trigger_config
        if image_urls is not None:
            row.image_urls = image_urls
        row.input_tokens = int(row.input_tokens or 0) + max(0, input_tokens_delta)
        row.output_tokens = int(row.output_tokens or 0) + max(0, output_tokens_delta)
        row.status = EyeOfGodJobStatus.COMPLETED.value
        row.error_message = None
        row.updated_at = now
        row.completed_at = now
        await self._session.commit()
        await self._session.refresh(row)
        return _job_view(row)
