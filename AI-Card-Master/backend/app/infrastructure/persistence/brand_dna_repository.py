"""SQLAlchemy adapters for BrandDNA persistence and successful-generation sampling."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.brand_dna import (
    BrandDNASignals,
    BrandDNAStatus,
    BrandDNAView,
    SuccessfulGenerationSample,
)
from app.domain.generation import GenerationJobStatus, SlideStatus
from app.models.brand_dna import BrandDNA
from app.models.generation_job import GenerationJob, GenerationSlide


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return tuple(items)


def _as_uuid_tuple(value: object) -> tuple[UUID, ...]:
    if not isinstance(value, list):
        return ()
    items: list[UUID] = []
    for item in value:
        try:
            items.append(item if isinstance(item, UUID) else UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return tuple(items)


def _to_view(row: BrandDNA) -> BrandDNAView:
    return BrandDNAView(
        id=row.id,
        user_id=row.user_id,
        status=BrandDNAStatus(row.status),
        is_active=bool(row.is_active),
        midjourney_context=row.midjourney_context,
        claude_context=row.claude_context,
        dominant_styles=_as_str_tuple(row.dominant_styles),
        palette_keywords=_as_str_tuple(row.palette_keywords),
        lighting_mood=_as_str_tuple(row.lighting_mood),
        composition_keywords=_as_str_tuple(row.composition_keywords),
        category_hints=_as_str_tuple(row.category_hints),
        sample_count=int(row.sample_count),
        source_job_ids=_as_uuid_tuple(row.source_job_ids),
        version=int(row.version),
        last_analyzed_at=(
            _to_utc(row.last_analyzed_at) if row.last_analyzed_at is not None else None
        ),
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
    )


class BrandDNARepository:
    """Persist BrandDNA profiles learned from successful seller generations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: UUID) -> BrandDNAView | None:
        row = await self._session.scalar(
            select(BrandDNA).where(BrandDNA.user_id == user_id)
        )
        return _to_view(row) if row is not None else None

    async def get_active_for_user(self, user_id: UUID) -> BrandDNAView | None:
        row = await self._session.scalar(
            select(BrandDNA).where(
                BrandDNA.user_id == user_id,
                BrandDNA.is_active.is_(True),
                BrandDNA.status.in_(
                    (BrandDNAStatus.READY.value, BrandDNAStatus.STALE.value)
                ),
            )
        )
        if row is None:
            return None
        if not (row.midjourney_context or row.claude_context):
            return None
        return _to_view(row)

    async def upsert_from_signals(
        self,
        *,
        user_id: UUID,
        signals: BrandDNASignals,
        midjourney_context: str,
        claude_context: str,
        status: BrandDNAStatus = BrandDNAStatus.READY,
        activate: bool = True,
    ) -> BrandDNAView:
        now = datetime.now(UTC)
        row = await self._session.scalar(
            select(BrandDNA).where(BrandDNA.user_id == user_id)
        )
        source_ids = [str(job_id) for job_id in signals.source_job_ids]
        if row is None:
            row = BrandDNA(
                user_id=user_id,
                status=status.value,
                is_active=activate,
                midjourney_context=midjourney_context,
                claude_context=claude_context,
                dominant_styles=list(signals.dominant_styles),
                palette_keywords=list(signals.palette_keywords),
                lighting_mood=list(signals.lighting_mood),
                composition_keywords=list(signals.composition_keywords),
                category_hints=list(signals.category_hints),
                source_job_ids=source_ids,
                sample_count=signals.sample_count,
                version=1,
                last_analyzed_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.status = status.value
            row.is_active = activate
            row.midjourney_context = midjourney_context
            row.claude_context = claude_context
            row.dominant_styles = list(signals.dominant_styles)
            row.palette_keywords = list(signals.palette_keywords)
            row.lighting_mood = list(signals.lighting_mood)
            row.composition_keywords = list(signals.composition_keywords)
            row.category_hints = list(signals.category_hints)
            row.source_job_ids = source_ids
            row.sample_count = signals.sample_count
            row.version = int(row.version) + 1
            row.last_analyzed_at = now
            row.updated_at = now
        await self._session.commit()
        await self._session.refresh(row)
        return _to_view(row)

    async def mark_analyzing(self, user_id: UUID) -> BrandDNAView | None:
        row = await self._session.scalar(
            select(BrandDNA).where(BrandDNA.user_id == user_id)
        )
        if row is None:
            now = datetime.now(UTC)
            row = BrandDNA(
                user_id=user_id,
                status=BrandDNAStatus.ANALYZING.value,
                is_active=True,
                sample_count=0,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.status = BrandDNAStatus.ANALYZING.value
            row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_view(row)

    async def set_active(self, *, user_id: UUID, is_active: bool) -> BrandDNAView | None:
        row = await self._session.scalar(
            select(BrandDNA).where(BrandDNA.user_id == user_id)
        )
        if row is None:
            return None
        row.is_active = is_active
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_view(row)


class SuccessfulGenerationsRepository:
    """Load completed generation jobs as BrandDNA learning samples."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_successful_samples(
        self,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[SuccessfulGenerationSample, ...]:
        result = await self._session.scalars(
            select(GenerationJob)
            .where(
                GenerationJob.user_id == user_id,
                GenerationJob.status == GenerationJobStatus.COMPLETED.value,
            )
            .options(selectinload(GenerationJob.slides))
            .order_by(GenerationJob.completed_at.desc().nullslast(), GenerationJob.created_at.desc())
            .limit(max(1, limit))
        )
        samples: list[SuccessfulGenerationSample] = []
        for job in result.all():
            slides = [
                slide
                for slide in (job.slides or [])
                if slide.status == SlideStatus.COMPLETED.value
            ]
            if not slides:
                continue
            slides_sorted = sorted(slides, key=lambda item: int(item.position))
            samples.append(
                SuccessfulGenerationSample(
                    job_id=job.id,
                    product_category=job.product_category,
                    selected_styles=tuple(
                        slide.selected_style
                        for slide in slides_sorted
                        if slide.selected_style
                    ),
                    prompts=tuple(
                        slide.prompt_used for slide in slides_sorted if slide.prompt_used
                    ),
                    completed_at=(
                        _to_utc(job.completed_at) if job.completed_at is not None else None
                    ),
                )
            )
        return tuple(samples)
