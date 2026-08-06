"""Automated A/B Testing API: 3 creatives → CTR week → keep winner."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.ab_test_service import (
    AbTestNotFoundError,
    AbTestService,
    AbTestValidationError,
)
from app.domain.ab_test import (
    AbCreativeStrategy,
    AbEnqueueRequest,
    AbExperimentStatus,
    AbProductBrief,
    AbTestConfig,
    AbVariantHypothesis,
    AbVariantStatus,
)
from app.infrastructure.ab_test_factory import build_ab_test_service
from app.infrastructure.celery_app import celery_app
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ab-tests", tags=["ab-testing"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AbTestCreateRequest(StrictAPIModel):
    product: AbProductBrief
    config: AbTestConfig | None = None


class AbVariantResponse(StrictAPIModel):
    id: UUID
    position: int
    strategy: AbCreativeStrategy
    status: AbVariantStatus
    title: str | None = None
    headline: str | None = None
    offer_hook: str | None = None
    main_image_brief: str | None = None
    rationale: str | None = None
    ads_creative_id: str | None = None
    ads_campaign_id: str | None = None
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    ctr_pct: float = Field(ge=0.0, le=100.0)
    spend: float | None = None
    metrics_sampled_at: str | None = None
    error_message: str | None = None


class AbExperimentResponse(StrictAPIModel):
    experiment_id: UUID
    status: AbExperimentStatus
    status_url: str
    marketplace: str
    niche_key: str
    sku: str
    model_name: str
    celery_task_id: str | None = None
    measurement_started_at: str | None = None
    measurement_ends_at: str | None = None
    winner_variant_id: UUID | None = None
    resolution_result: dict[str, Any] | None = None
    hypotheses: list[dict[str, Any]] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None
    variants: tuple[AbVariantResponse, ...] = ()
    idempotent_replay: bool = False


class AbEnqueueResponse(StrictAPIModel):
    experiment_id: UUID
    status: AbExperimentStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    strategies: list[AbCreativeStrategy]
    duration_days: int = Field(ge=1)
    preview_titles: list[str] = Field(default_factory=list)


class AbResolveRequest(StrictAPIModel):
    force: bool = False


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> AbTestService:
    return build_ab_test_service(db_session)


def _variant_response(variant) -> AbVariantResponse:
    return AbVariantResponse(
        id=variant.id,
        position=variant.position,
        strategy=variant.strategy,
        status=variant.status,
        title=variant.title,
        headline=variant.headline,
        offer_hook=variant.offer_hook,
        main_image_brief=variant.main_image_brief,
        rationale=variant.rationale,
        ads_creative_id=variant.ads_creative_id,
        ads_campaign_id=variant.ads_campaign_id,
        impressions=variant.impressions,
        clicks=variant.clicks,
        ctr_pct=variant.ctr_pct,
        spend=variant.spend,
        metrics_sampled_at=(
            variant.metrics_sampled_at.isoformat()
            if variant.metrics_sampled_at
            else None
        ),
        error_message=variant.error_message,
    )


def _experiment_response(
    experiment, *, idempotent_replay: bool = False
) -> AbExperimentResponse:
    return AbExperimentResponse(
        experiment_id=experiment.id,
        status=experiment.status,
        status_url=f"/api/v1/ab-tests/{experiment.id}",
        marketplace=experiment.marketplace,
        niche_key=experiment.niche_key,
        sku=experiment.sku,
        model_name=experiment.model_name,
        celery_task_id=experiment.celery_task_id,
        measurement_started_at=(
            experiment.measurement_started_at.isoformat()
            if experiment.measurement_started_at
            else None
        ),
        measurement_ends_at=(
            experiment.measurement_ends_at.isoformat()
            if experiment.measurement_ends_at
            else None
        ),
        winner_variant_id=experiment.winner_variant_id,
        resolution_result=experiment.resolution_result,
        hypotheses=experiment.hypotheses_payload,
        error_message=experiment.error_message,
        input_tokens=experiment.input_tokens,
        output_tokens=experiment.output_tokens,
        created_at=experiment.created_at.isoformat(),
        updated_at=experiment.updated_at.isoformat(),
        completed_at=(
            experiment.completed_at.isoformat() if experiment.completed_at else None
        ),
        variants=tuple(_variant_response(v) for v in experiment.variants),
        idempotent_replay=idempotent_replay,
    )


@router.post(
    "/preview",
    response_model=list[AbVariantHypothesis],
    summary="Preview three deterministic main-card hypotheses",
)
async def preview_ab_hypotheses(
    body: AbTestCreateRequest,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> list[AbVariantHypothesis]:
    """Return pain_hook / social_proof / offer_urgency drafts without Claude spend."""

    _ = current_user
    try:
        request = AbEnqueueRequest(product=body.product, config=body.config)
        return list(service.preview_hypotheses(request))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except AbTestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "",
    response_model=AbEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue automated A/B test (3 creatives → CTR week → keep winner)",
)
async def enqueue_ab_experiment(
    body: AbTestCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> AbEnqueueResponse:
    """Generate 3 strategies, publish to ads cabinet, measure CTR for N days."""

    try:
        request = AbEnqueueRequest(product=body.product, config=body.config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    preview = service.preview_hypotheses(request)
    duration_days = (request.config or AbTestConfig()).duration_days

    try:
        experiment, replay = await service.enqueue_experiment(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except AbTestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = experiment.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "ab_test.generate_and_publish",
            args=[str(experiment.id)],
            queue="ab_test",
        )
        celery_task_id = async_result.id
        experiment = await service.attach_celery_task(
            experiment_id=experiment.id,
            celery_task_id=celery_task_id,
        )

    return AbEnqueueResponse(
        experiment_id=experiment.id,
        status=experiment.status,
        status_url=f"/api/v1/ab-tests/{experiment.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        strategies=[h.strategy for h in preview],
        duration_days=duration_days,
        preview_titles=[h.title for h in preview],
    )


@router.get(
    "",
    response_model=list[AbExperimentResponse],
    summary="List recent A/B experiments for the current seller",
)
async def list_ab_experiments(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> list[AbExperimentResponse]:
    rows = await service.list_experiments_for_user(
        user_id=current_user.id,
        limit=limit,
    )
    return [_experiment_response(row) for row in rows]


@router.get(
    "/{experiment_id}",
    response_model=AbExperimentResponse,
    summary="Poll A/B experiment status, CTR, and resolution",
)
async def get_ab_experiment(
    experiment_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> AbExperimentResponse:
    try:
        experiment = await service.get_experiment_for_user(
            user_id=current_user.id,
            experiment_id=experiment_id,
        )
    except AbTestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _experiment_response(experiment)


@router.post(
    "/{experiment_id}/refresh-metrics",
    response_model=AbExperimentResponse,
    summary="Pull fresh CTR snapshots from the ads cabinet",
)
async def refresh_ab_metrics(
    experiment_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> AbExperimentResponse:
    try:
        await service.get_experiment_for_user(
            user_id=current_user.id,
            experiment_id=experiment_id,
        )
        experiment = await service.refresh_metrics(experiment_id=experiment_id)
    except AbTestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AbTestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _experiment_response(experiment)


@router.post(
    "/{experiment_id}/resolve",
    response_model=AbExperimentResponse,
    summary="Keep best CTR variant and delete losers",
)
async def resolve_ab_experiment(
    experiment_id: UUID,
    body: AbResolveRequest | None = None,
    current_user: User = Depends(get_current_user),
    service: AbTestService = Depends(_get_service),
) -> AbExperimentResponse:
    force = body.force if body is not None else False
    try:
        await service.get_experiment_for_user(
            user_id=current_user.id,
            experiment_id=experiment_id,
        )
        experiment = await service.resolve_experiment(
            experiment_id=experiment_id,
            force=force,
        )
    except AbTestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AbTestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _experiment_response(experiment)
