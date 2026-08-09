"""Market Gap & Trend Prediction (The Oracle) API."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.oracle_service import (
    OracleNotFoundError,
    OracleService,
    OracleValidationError,
)
from app.domain.oracle import (
    OracleEnqueueRequest,
    OracleGapConfig,
    OracleJobStatus,
    OracleScanReport,
    SearchQuerySignal,
    SupplyCardSignal,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.oracle_factory import build_oracle_service
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-market-gap"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OraclePredictRequest(StrictAPIModel):
    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    search_queries: list[SearchQuerySignal] = Field(min_length=1, max_length=500)
    supply_cards: list[SupplyCardSignal] = Field(default_factory=list, max_length=500)
    gap_config: OracleGapConfig | None = None


class OracleEnqueueResponse(StrictAPIModel):
    task_id: UUID
    status: OracleJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    opportunity_preview_count: int = Field(ge=0)
    notification_preview: list[str] = Field(default_factory=list)


class OracleJobResponse(StrictAPIModel):
    task_id: UUID
    status: OracleJobStatus
    status_url: str
    niche_key: str
    marketplace: str
    model_name: str
    celery_task_id: str | None = None
    scan_report: dict[str, Any] | None = None
    prediction_result: dict[str, Any] | None = None
    notifications: list[str] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None


class OracleNotificationItem(StrictAPIModel):
    job_id: UUID
    niche_key: str
    marketplace: str
    message: str
    created_at: str


class OracleNotificationsResponse(StrictAPIModel):
    items: list[OracleNotificationItem]
    total: int = Field(ge=0)


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> OracleService:
    return build_oracle_service(db_session)


def _job_response(job) -> OracleJobResponse:
    return OracleJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/oracle/{job.id}",
        niche_key=job.niche_key,
        marketplace=job.marketplace,
        model_name=job.model_name,
        celery_task_id=job.celery_task_id,
        scan_report=job.scan_report,
        prediction_result=job.prediction_result,
        notifications=job.notifications,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _to_enqueue_request(body: OraclePredictRequest) -> OracleEnqueueRequest:
    return OracleEnqueueRequest(
        niche_key=body.niche_key,
        marketplace=body.marketplace,
        search_queries=body.search_queries,
        supply_cards=body.supply_cards,
        gap_config=body.gap_config,
    )


@router.post(
    "/preview",
    response_model=OracleScanReport,
    summary="Preview market-gap scan without Claude spend",
)
async def preview_oracle_scan(
    body: OraclePredictRequest,
    current_user: User = Depends(get_current_user),
    service: OracleService = Depends(_get_service),
) -> OracleScanReport:
    """Compare rising search demand with scarce top-card supply (sync)."""

    _ = current_user
    try:
        return service.preview_scan(_to_enqueue_request(body))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except OracleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/predict",
    response_model=OracleEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue The Oracle market-gap prediction",
)
async def enqueue_oracle_prediction(
    body: OraclePredictRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: OracleService = Depends(_get_service),
) -> OracleEnqueueResponse:
    """Scan demand vs supply → Claude enrichment → niche notifications."""

    request = _to_enqueue_request(body)
    preview = service.preview_scan(request)

    try:
        job, replay = await service.enqueue_prediction(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except OracleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "claude.run_oracle_prediction",
            args=[str(job.id)],
            queue="claude.reasoning",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return OracleEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/oracle/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        opportunity_preview_count=len(preview.opportunities),
        notification_preview=[
            gap.notification_message for gap in preview.opportunities
        ],
    )


@router.get(
    "/notifications",
    response_model=OracleNotificationsResponse,
    summary="List recent niche alerts from The Oracle",
)
async def list_oracle_notifications(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    current_user: User = Depends(get_current_user),
    service: OracleService = Depends(_get_service),
) -> OracleNotificationsResponse:
    """Return flattened «Обнаружена ниша!» messages for the current user."""

    raw = await service.list_notifications(user_id=current_user.id, limit=limit)
    items = [
        OracleNotificationItem(
            job_id=UUID(item["job_id"]),
            niche_key=item["niche_key"],
            marketplace=item["marketplace"],
            message=item["message"],
            created_at=item["created_at"],
        )
        for item in raw
    ]
    return OracleNotificationsResponse(items=items, total=len(items))


@router.get(
    "/{task_id}",
    response_model=OracleJobResponse,
    summary="Poll Oracle prediction job / niche notifications",
)
async def get_oracle_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: OracleService = Depends(_get_service),
) -> OracleJobResponse:
    """Return scan report, prediction result, and niche alert messages."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except OracleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _job_response(job)
