"""Strategic 'Killer' Recommendations Engine (AI Strategy) API."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.ai_strategy_service import (
    StrategyNotFoundError,
    StrategyService,
    StrategyValidationError,
)
from app.domain.ai_strategy import (
    StrategyCardSnapshot,
    StrategyCompareConfig,
    StrategyCompareReport,
    StrategyEnqueueRequest,
    StrategyJobStatus,
)
from app.infrastructure.ai_strategy_factory import build_ai_strategy_service
from app.infrastructure.celery_app import celery_app
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai-strategy", tags=["ai-strategy-killer"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StrategyPlanRequest(StrictAPIModel):
    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    user_card: StrategyCardSnapshot
    leader_card: StrategyCardSnapshot
    compare_config: StrategyCompareConfig | None = None


class StrategyEnqueueResponse(StrictAPIModel):
    task_id: UUID
    status: StrategyJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    recommendation_preview_count: int = Field(ge=0)
    total_ctr_lift_pct: float
    rationale_preview: list[str] = Field(default_factory=list)


class StrategyJobResponse(StrictAPIModel):
    task_id: UUID
    status: StrategyJobStatus
    status_url: str
    niche_key: str
    marketplace: str
    model_name: str
    celery_task_id: str | None = None
    compare_report: dict[str, Any] | None = None
    plan_result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> StrategyService:
    return build_ai_strategy_service(db_session)


def _job_response(job) -> StrategyJobResponse:
    return StrategyJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/ai-strategy/{job.id}",
        niche_key=job.niche_key,
        marketplace=job.marketplace,
        model_name=job.model_name,
        celery_task_id=job.celery_task_id,
        compare_report=job.compare_report,
        plan_result=job.plan_result,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _to_enqueue_request(body: StrategyPlanRequest) -> StrategyEnqueueRequest:
    return StrategyEnqueueRequest(
        niche_key=body.niche_key,
        marketplace=body.marketplace,
        user_card=body.user_card,
        leader_card=body.leader_card,
        compare_config=body.compare_config,
    )


@router.post(
    "/preview",
    response_model=StrategyCompareReport,
    summary="Preview user-vs-leader comparison without Claude spend",
)
async def preview_strategy_compare(
    body: StrategyPlanRequest,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(_get_service),
) -> StrategyCompareReport:
    """Diff seller card vs niche leader → ordered killer steps with CTR rationale."""

    _ = current_user
    try:
        return service.preview_compare(_to_enqueue_request(body))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except StrategyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/plan",
    response_model=StrategyEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue AI Strategy killer recommendations plan",
)
async def enqueue_strategy_plan(
    body: StrategyPlanRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(_get_service),
) -> StrategyEnqueueResponse:
    """Compare cards → Claude step plan (background → title) with CTR rationale."""

    try:
        request = _to_enqueue_request(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    preview = service.preview_compare(request)

    try:
        job, replay = await service.enqueue_plan(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except StrategyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "claude.run_ai_strategy_plan",
            args=[str(job.id)],
            queue="claude.reasoning",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return StrategyEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/ai-strategy/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        recommendation_preview_count=len(preview.recommendations),
        total_ctr_lift_pct=preview.total_ctr_lift_pct,
        rationale_preview=[rec.rationale for rec in preview.recommendations],
    )


@router.get(
    "/{task_id}",
    response_model=StrategyJobResponse,
    summary="Poll AI Strategy job / killer plan",
)
async def get_strategy_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: StrategyService = Depends(_get_service),
) -> StrategyJobResponse:
    """Return compare report and step-by-step killer recommendations."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except StrategyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _job_response(job)
