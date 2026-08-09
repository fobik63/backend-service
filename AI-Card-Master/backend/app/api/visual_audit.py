"""Claude 4.7 intelligent visual audit API: filter top-N → Rising Stars → generator JSON."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.visual_audit_service import (
    VisualAuditNotFoundError,
    VisualAuditService,
    VisualAuditValidationError,
)
from app.domain.visual_audit import (
    NicheCardSignal,
    NicheFilterReport,
    VisualAuditEnqueueRequest,
    VisualAuditFilterConfig,
    VisualAuditJobStatus,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.visual_audit_factory import build_visual_audit_service
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/claude/visual-audit", tags=["claude-visual-audit"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VisualAuditPreviewRequest(StrictAPIModel):
    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    cards: list[NicheCardSignal] = Field(min_length=1, max_length=200)
    filter_config: VisualAuditFilterConfig | None = None


class VisualAuditEnqueueResponse(StrictAPIModel):
    task_id: UUID
    status: VisualAuditJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    rising_star_preview_count: int = Field(ge=0)
    brand_dominant_excluded_count: int = Field(ge=0)


class VisualAuditJobResponse(StrictAPIModel):
    task_id: UUID
    status: VisualAuditJobStatus
    status_url: str
    niche_key: str
    marketplace: str
    model_name: str
    celery_task_id: str | None = None
    filter_report: dict[str, Any] | None = None
    vision_dissections: list[dict[str, Any]] | None = None
    generator_config: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> VisualAuditService:
    return build_visual_audit_service(db_session)


def _job_response(job) -> VisualAuditJobResponse:
    return VisualAuditJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude/visual-audit/{job.id}",
        niche_key=job.niche_key,
        marketplace=job.marketplace,
        model_name=job.model_name,
        celery_task_id=job.celery_task_id,
        filter_report=job.filter_report,
        vision_dissections=job.vision_dissections,
        generator_config=job.generator_config,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.post(
    "/preview-filter",
    response_model=NicheFilterReport,
    summary="Preview Brand Dominant / Rising Star filter without Claude spend",
)
async def preview_visual_audit_filter(
    body: VisualAuditPreviewRequest,
    current_user: User = Depends(get_current_user),
    service: VisualAuditService = Depends(_get_service),
) -> NicheFilterReport:
    """Strict review/sales filter for top niche cards (sync, no Vision)."""

    _ = current_user
    request = VisualAuditEnqueueRequest(
        niche_key=body.niche_key,
        marketplace=body.marketplace,
        cards=body.cards,
        filter_config=body.filter_config,
    )
    try:
        return service.preview_filter(request)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except VisualAuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/analyze",
    response_model=VisualAuditEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue intelligent visual audit for niche top cards",
)
async def enqueue_visual_audit(
    body: VisualAuditPreviewRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: VisualAuditService = Depends(_get_service),
) -> VisualAuditEnqueueResponse:
    """Filter top-N → dissect Rising Stars via Claude Vision → generator JSON."""

    request = VisualAuditEnqueueRequest(
        niche_key=body.niche_key,
        marketplace=body.marketplace,
        cards=body.cards,
        filter_config=body.filter_config,
    )
    preview = service.preview_filter(request)

    try:
        job, replay = await service.enqueue_audit(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except VisualAuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "claude.run_visual_audit",
            args=[str(job.id)],
            queue="claude.reasoning",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return VisualAuditEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude/visual-audit/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        rising_star_preview_count=len(preview.rising_stars),
        brand_dominant_excluded_count=len(preview.brand_dominant),
    )


@router.get(
    "/{task_id}",
    response_model=VisualAuditJobResponse,
    summary="Poll visual-audit job / generator JSON config",
)
async def get_visual_audit_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: VisualAuditService = Depends(_get_service),
) -> VisualAuditJobResponse:
    """Return filter report, Rising Star dissections, and generator_config."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except VisualAuditNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _job_response(job)
