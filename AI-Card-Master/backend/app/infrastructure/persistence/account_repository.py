"""SQLAlchemy adapter for GDPR account erasure."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bulk_generation import BulkGenerationBatch, BulkGenerationItem
from app.models.claude_reasoning import ClaudeReasoningJob
from app.models.generation_job import GenerationJob, GenerationSlide
from app.models.smart_variant import SmartVariantItem, SmartVariantSync
from app.models.user import User


def _normalize_keys(values: list[str | None]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        key = raw.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return unique


class AccountRepository:
    """Collect storage keys and hard-delete the user aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_credentials(self, user_id: UUID) -> tuple[str, str] | None:
        row = await self._session.execute(
            select(User.email, User.hashed_password).where(User.id == user_id)
        )
        found = row.one_or_none()
        if found is None:
            return None
        return str(found.email), str(found.hashed_password)

    async def collect_storage_object_keys(self, user_id: UUID) -> list[str]:
        keys: list[str | None] = []

        job_rows = await self._session.execute(
            select(
                GenerationJob.input_object_key,
                GenerationJob.archive_object_key,
                GenerationJob.thumbnail_object_key,
            ).where(GenerationJob.user_id == user_id)
        )
        for input_key, archive_key, thumb_key in job_rows.all():
            keys.extend([input_key, archive_key, thumb_key])

        slide_rows = await self._session.execute(
            select(GenerationSlide.result_object_key)
            .join(GenerationJob, GenerationSlide.job_id == GenerationJob.id)
            .where(GenerationJob.user_id == user_id)
        )
        keys.extend(slide_rows.scalars().all())

        bulk_rows = await self._session.execute(
            select(BulkGenerationBatch.source_zip_object_key).where(
                BulkGenerationBatch.user_id == user_id
            )
        )
        keys.extend(bulk_rows.scalars().all())

        bulk_item_rows = await self._session.execute(
            select(BulkGenerationItem.input_object_key)
            .join(
                BulkGenerationBatch,
                BulkGenerationItem.batch_id == BulkGenerationBatch.id,
            )
            .where(BulkGenerationBatch.user_id == user_id)
        )
        keys.extend(bulk_item_rows.scalars().all())

        sync_rows = await self._session.execute(
            select(SmartVariantSync.source_image_object_key).where(
                SmartVariantSync.user_id == user_id
            )
        )
        keys.extend(sync_rows.scalars().all())

        variant_rows = await self._session.execute(
            select(SmartVariantItem.recolored_object_key)
            .join(SmartVariantSync, SmartVariantItem.sync_id == SmartVariantSync.id)
            .where(SmartVariantSync.user_id == user_id)
        )
        keys.extend(variant_rows.scalars().all())

        claude_rows = await self._session.execute(
            select(ClaudeReasoningJob.image_object_keys).where(
                ClaudeReasoningJob.user_id == user_id
            )
        )
        for payload in claude_rows.scalars().all():
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, str):
                        keys.append(item)

        return _normalize_keys(keys)

    async def delete_user(self, user_id: UUID) -> bool:
        result = await self._session.execute(delete(User).where(User.id == user_id))
        await self._session.commit()
        return bool(result.rowcount)
