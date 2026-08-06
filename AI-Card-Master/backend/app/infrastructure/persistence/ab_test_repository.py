"""SQLAlchemy adapter for Automated A/B Testing persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.ab_test import (
    AbCreativeStrategy,
    AbExperimentStatus,
    AbExperimentView,
    AbVariantMetrics,
    AbVariantStatus,
    AbVariantView,
)
from app.models.ab_test import AbTestExperiment, AbTestVariant


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _variant_view(row: AbTestVariant) -> AbVariantView:
    return AbVariantView(
        id=row.id,
        experiment_id=row.experiment_id,
        position=row.position,
        strategy=AbCreativeStrategy(row.strategy),
        status=AbVariantStatus(row.status),
        title=row.title,
        main_image_brief=row.main_image_brief,
        offer_hook=row.offer_hook,
        headline=row.headline,
        rationale=row.rationale,
        prompt_for_generator=row.prompt_for_generator,
        confidence=row.confidence,
        ads_creative_id=row.ads_creative_id,
        ads_campaign_id=row.ads_campaign_id,
        marketplace_media_id=row.marketplace_media_id,
        impressions=row.impressions,
        clicks=row.clicks,
        ctr_pct=float(row.ctr_pct or 0.0),
        spend=row.spend,
        metrics_sampled_at=(
            _to_utc(row.metrics_sampled_at) if row.metrics_sampled_at else None
        ),
        error_message=row.error_message,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
    )


def _experiment_view(
    row: AbTestExperiment, *, include_variants: bool = True
) -> AbExperimentView:
    variants: tuple[AbVariantView, ...] = ()
    if include_variants and row.variants is not None:
        variants = tuple(_variant_view(v) for v in row.variants)
    return AbExperimentView(
        id=row.id,
        user_id=row.user_id,
        status=AbExperimentStatus(row.status),
        celery_task_id=row.celery_task_id,
        marketplace=row.marketplace,
        niche_key=row.niche_key,
        sku=row.sku,
        nm_id=row.nm_id,
        campaign_id=row.campaign_id,
        model_name=row.model_name,
        product_payload=dict(row.product_payload or {}),
        config=dict(row.config or {}),
        hypotheses_payload=(
            list(row.hypotheses_payload) if row.hypotheses_payload is not None else None
        ),
        resolution_result=(
            dict(row.resolution_result) if row.resolution_result else None
        ),
        winner_variant_id=row.winner_variant_id,
        measurement_started_at=(
            _to_utc(row.measurement_started_at) if row.measurement_started_at else None
        ),
        measurement_ends_at=(
            _to_utc(row.measurement_ends_at) if row.measurement_ends_at else None
        ),
        error_message=row.error_message,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        completed_at=_to_utc(row.completed_at) if row.completed_at else None,
        variants=variants,
    )


class AbTestRepository:
    """Persist A/B experiments and creative variants."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_experiment(
        self,
        *,
        user_id: UUID,
        marketplace: str,
        niche_key: str,
        sku: str,
        nm_id: str | None,
        campaign_id: str | None,
        product_payload: dict[str, Any],
        config: dict[str, Any],
        model_name: str,
        strategies: tuple[AbCreativeStrategy, ...],
        idempotency_key: str | None = None,
    ) -> AbExperimentView:
        row = AbTestExperiment(
            user_id=user_id,
            idempotency_key=idempotency_key,
            status=AbExperimentStatus.QUEUED.value,
            model_name=model_name,
            marketplace=marketplace,
            niche_key=niche_key,
            sku=sku,
            nm_id=nm_id,
            campaign_id=campaign_id,
            product_payload=product_payload,
            config=config,
        )
        for position, strategy in enumerate(strategies):
            row.variants.append(
                AbTestVariant(
                    position=position,
                    strategy=strategy.value,
                    status=AbVariantStatus.PENDING.value,
                )
            )
        self._session.add(row)
        await self._session.commit()
        return await self._reload(row.id)

    async def find_idempotent_experiment(
        self, *, user_id: UUID, idempotency_key: str
    ) -> AbExperimentView | None:
        row = await self._session.scalar(
            select(AbTestExperiment)
            .options(selectinload(AbTestExperiment.variants))
            .where(
                AbTestExperiment.user_id == user_id,
                AbTestExperiment.idempotency_key == idempotency_key,
            )
        )
        return _experiment_view(row) if row is not None else None

    async def get_experiment_for_user(
        self, *, user_id: UUID, experiment_id: UUID
    ) -> AbExperimentView | None:
        row = await self._session.scalar(
            select(AbTestExperiment)
            .options(selectinload(AbTestExperiment.variants))
            .where(
                AbTestExperiment.id == experiment_id,
                AbTestExperiment.user_id == user_id,
            )
        )
        return _experiment_view(row) if row is not None else None

    async def get_experiment(
        self, *, experiment_id: UUID, include_variants: bool = True
    ) -> AbExperimentView | None:
        stmt = select(AbTestExperiment).where(AbTestExperiment.id == experiment_id)
        if include_variants:
            stmt = stmt.options(selectinload(AbTestExperiment.variants))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _experiment_view(row, include_variants=include_variants)

    async def list_experiments_for_user(
        self, *, user_id: UUID, limit: int = 20
    ) -> tuple[AbExperimentView, ...]:
        rows = (
            await self._session.scalars(
                select(AbTestExperiment)
                .options(selectinload(AbTestExperiment.variants))
                .where(AbTestExperiment.user_id == user_id)
                .order_by(AbTestExperiment.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).all()
        return tuple(_experiment_view(row) for row in rows)

    async def list_active_measuring(
        self, *, limit: int = 50
    ) -> tuple[AbExperimentView, ...]:
        rows = (
            await self._session.scalars(
                select(AbTestExperiment)
                .options(selectinload(AbTestExperiment.variants))
                .where(AbTestExperiment.status == AbExperimentStatus.MEASURING.value)
                .order_by(AbTestExperiment.measurement_ends_at.asc().nulls_last())
                .limit(max(1, min(limit, 200)))
            )
        ).all()
        return tuple(_experiment_view(row) for row in rows)

    async def list_due_for_resolution(
        self, *, now: datetime, limit: int = 50
    ) -> tuple[AbExperimentView, ...]:
        clock = now if now.tzinfo else now.replace(tzinfo=UTC)
        rows = (
            await self._session.scalars(
                select(AbTestExperiment)
                .options(selectinload(AbTestExperiment.variants))
                .where(
                    AbTestExperiment.status == AbExperimentStatus.MEASURING.value,
                    AbTestExperiment.measurement_ends_at.is_not(None),
                    AbTestExperiment.measurement_ends_at <= clock.astimezone(UTC),
                )
                .order_by(AbTestExperiment.measurement_ends_at.asc())
                .limit(max(1, min(limit, 200)))
            )
        ).all()
        return tuple(_experiment_view(row) for row in rows)

    async def mark_status(
        self,
        *,
        experiment_id: UUID,
        status: AbExperimentStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
        measurement_started_at: datetime | None = None,
        measurement_ends_at: datetime | None = None,
        winner_variant_id: UUID | None = None,
        resolution_result: dict[str, Any] | None = None,
    ) -> AbExperimentView:
        row = await self._require(experiment_id)
        row.status = status.value
        row.updated_at = datetime.now(UTC)
        if celery_task_id is not None:
            row.celery_task_id = celery_task_id
        if error_message is not None:
            row.error_message = error_message
        if completed_at is not None:
            row.completed_at = completed_at
        if measurement_started_at is not None:
            row.measurement_started_at = measurement_started_at
        if measurement_ends_at is not None:
            row.measurement_ends_at = measurement_ends_at
        if winner_variant_id is not None:
            row.winner_variant_id = winner_variant_id
        if resolution_result is not None:
            row.resolution_result = resolution_result
        await self._session.commit()
        return await self._reload(experiment_id)

    async def save_hypotheses(
        self,
        *,
        experiment_id: UUID,
        hypotheses: list[dict[str, Any]],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> AbExperimentView:
        row = await self._require(experiment_id, with_variants=True)
        row.hypotheses_payload = hypotheses
        row.input_tokens = max(0, row.input_tokens + max(0, input_tokens_delta))
        row.output_tokens = max(0, row.output_tokens + max(0, output_tokens_delta))
        row.updated_at = datetime.now(UTC)

        by_strategy = {
            str(item.get("strategy")): item
            for item in hypotheses
            if isinstance(item, dict) and item.get("strategy")
        }
        for variant in row.variants:
            payload = by_strategy.get(variant.strategy)
            if not payload:
                continue
            variant.title = str(payload.get("title") or "")[:200] or None
            variant.main_image_brief = (
                str(payload.get("main_image_brief") or "")[:800] or None
            )
            variant.offer_hook = str(payload.get("offer_hook") or "")[:300] or None
            variant.headline = str(payload.get("headline") or "")[:200] or None
            variant.rationale = str(payload.get("rationale") or "")[:500] or None
            variant.prompt_for_generator = (
                str(payload.get("prompt_for_generator") or "")[:1200] or None
            )
            conf = payload.get("confidence")
            variant.confidence = float(conf) if isinstance(conf, (int, float)) else None
            variant.status = AbVariantStatus.GENERATED.value
            variant.updated_at = datetime.now(UTC)

        await self._session.commit()
        return await self._reload(experiment_id)

    async def update_variant(
        self,
        *,
        variant_id: UUID,
        status: AbVariantStatus | None = None,
        ads_creative_id: str | None = None,
        ads_campaign_id: str | None = None,
        marketplace_media_id: str | None = None,
        metrics: AbVariantMetrics | None = None,
        error_message: str | None = None,
        clear_error: bool = False,
    ) -> AbVariantView:
        row = await self._session.scalar(
            select(AbTestVariant).where(AbTestVariant.id == variant_id)
        )
        if row is None:
            raise ValueError(f"A/B variant not found: {variant_id}")
        row.updated_at = datetime.now(UTC)
        if status is not None:
            row.status = status.value
        if ads_creative_id is not None:
            row.ads_creative_id = ads_creative_id[:128]
        if ads_campaign_id is not None:
            row.ads_campaign_id = ads_campaign_id[:128]
        if marketplace_media_id is not None:
            row.marketplace_media_id = marketplace_media_id[:128]
        if metrics is not None:
            row.impressions = metrics.impressions
            row.clicks = metrics.clicks
            row.ctr_pct = metrics.ctr_pct
            row.spend = metrics.spend
            row.metrics_sampled_at = metrics.sampled_at or datetime.now(UTC)
        if clear_error:
            row.error_message = None
        if error_message is not None:
            row.error_message = error_message[:2000]
        await self._session.commit()
        await self._session.refresh(row)
        return _variant_view(row)

    async def save_final_resolution(
        self,
        *,
        experiment_id: UUID,
        resolution_result: dict[str, Any],
        winner_variant_id: UUID | None,
        winner_status: AbVariantStatus,
        loser_ids: list[UUID],
        deleted_ids: list[UUID],
    ) -> AbExperimentView:
        row = await self._require(experiment_id, with_variants=True)
        now = datetime.now(UTC)
        row.resolution_result = resolution_result
        row.winner_variant_id = winner_variant_id
        row.status = AbExperimentStatus.COMPLETED.value
        row.completed_at = now
        row.updated_at = now

        deleted_set = set(deleted_ids)
        loser_set = set(loser_ids)
        for variant in row.variants:
            variant.updated_at = now
            if winner_variant_id is not None and variant.id == winner_variant_id:
                variant.status = winner_status.value
            elif variant.id in deleted_set:
                variant.status = AbVariantStatus.DELETED.value
            elif variant.id in loser_set:
                variant.status = AbVariantStatus.LOSER.value

        await self._session.commit()
        return await self._reload(experiment_id)

    async def _require(
        self, experiment_id: UUID, *, with_variants: bool = False
    ) -> AbTestExperiment:
        stmt = select(AbTestExperiment).where(AbTestExperiment.id == experiment_id)
        if with_variants:
            stmt = stmt.options(selectinload(AbTestExperiment.variants))
        row = await self._session.scalar(stmt)
        if row is None:
            raise ValueError(f"A/B experiment not found: {experiment_id}")
        return row

    async def _reload(self, experiment_id: UUID) -> AbExperimentView:
        view = await self.get_experiment(experiment_id=experiment_id)
        if view is None:
            raise ValueError(f"A/B experiment not found: {experiment_id}")
        return view
