"""Competitor negative-review pain analysis API (plan §71)."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.pain_analysis_service import (
    PainAnalysisNotFoundError,
    PainAnalysisService,
    PainAnalysisValidationError,
)
from app.domain.pain_analysis import (
    PainAnalysisJobStatus,
    PainAnalysisRequest,
    PainAnalysisResult,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.pain_analysis_factory import build_pain_analysis_service
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pain-analysis", tags=["pain-analysis"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PainAnalysisBody(StrictAPIModel):
    product_name: str = Field(min_length=1, max_length=300)
    product_specs: str = Field(default="", max_length=4000)
    platform: str = Field(min_length=1, max_length=32)
    raw_negative_reviews: list[str] = Field(min_length=1, max_length=100)


class PainAnalysisEnqueueResponse(StrictAPIModel):
    task_id: UUID
    status: PainAnalysisJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    junk_preview_count: int = Field(ge=0)
    pain_preview_count: int = Field(ge=0)
    pain_preview: list[str] = Field(default_factory=list)


class PainAnalysisJobResponse(StrictAPIModel):
    task_id: UUID
    status: PainAnalysisJobStatus
    status_url: str
    product_name: str
    platform: str
    model_name: str
    celery_task_id: str | None = None
    filter_preview: dict[str, Any] | None = None
    analysis_result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> PainAnalysisService:
    return build_pain_analysis_service(db_session)


def _job_response(job) -> PainAnalysisJobResponse:
    return PainAnalysisJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/pain-analysis/{job.id}",
        product_name=job.product_name,
        platform=job.platform,
        model_name=job.model_name,
        celery_task_id=job.celery_task_id,
        filter_preview=job.filter_preview,
        analysis_result=job.analysis_result,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _to_request(body: PainAnalysisBody) -> PainAnalysisRequest:
    return PainAnalysisRequest(
        product_name=body.product_name,
        product_specs=body.product_specs,
        platform=body.platform,
        raw_negative_reviews=body.raw_negative_reviews,
    )


@router.post(
    "/preview",
    response_model=PainAnalysisResult,
    summary="Preview junk filter + template badges/SEO without Claude spend",
)
async def preview_pain_analysis(
    body: PainAnalysisBody,
    current_user: User = Depends(get_current_user),
    service: PainAnalysisService = Depends(_get_service),
) -> PainAnalysisResult:
    """Deterministically filter competitor negatives and draft pain-closing content."""

    _ = current_user
    try:
        return service.preview_filter(_to_request(body))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except PainAnalysisValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/analyze",
    response_model=PainAnalysisEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue Claude pain analysis of competitor negative reviews",
)
async def enqueue_pain_analysis(
    body: PainAnalysisBody,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: PainAnalysisService = Depends(_get_service),
) -> PainAnalysisEnqueueResponse:
    """Filter junk → extract real pains → badges + SEO (background Claude job)."""

    try:
        request = _to_request(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    preview = service.preview_filter(request)
    pain_preview = (
        []
        if preview.insufficient_data
        else list(preview.real_product_pains)
    )

    try:
        job, replay = await service.enqueue_analysis(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except PainAnalysisValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "claude.run_pain_analysis",
            args=[str(job.id)],
            queue="claude.reasoning",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return PainAnalysisEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/pain-analysis/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        junk_preview_count=len(preview.filtered_out_junk),
        pain_preview_count=len(pain_preview),
        pain_preview=pain_preview,
    )


@router.get(
    "/{job_id}",
    response_model=PainAnalysisJobResponse,
    summary="Get pain-analysis job status and result",
)
async def get_pain_analysis_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    service: PainAnalysisService = Depends(_get_service),
) -> PainAnalysisJobResponse:
    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=job_id)
    except PainAnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _job_response(job)
