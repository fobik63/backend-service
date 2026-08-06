"""Claude 4.7 Vision & Reasoning API: async CoT competitor analysis."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.claude_reasoning_service import (
    ClaudeReasoningNotFoundError,
    ClaudeReasoningService,
    ClaudeReasoningValidationError,
)
from app.domain.claude_reasoning import (
    ClaudeReasoningJobStatus,
    CompetitorTextContext,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.claude_reasoning_factory import build_claude_reasoning_service
from app.models.database import get_db_session
from app.models.user import User
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/claude/reasoning", tags=["claude-reasoning"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClaudeReasoningEnqueueResponse(StrictAPIModel):
    task_id: UUID
    status: ClaudeReasoningJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False


class ClaudeReasoningJobResponse(StrictAPIModel):
    task_id: UUID
    status: ClaudeReasoningJobStatus
    status_url: str
    model_name: str
    celery_task_id: str | None = None
    vision_result: dict[str, Any] | None = None
    reasoning_result: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: str
    updated_at: str
    completed_at: str | None = None


def _get_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> ClaudeReasoningService:
    return build_claude_reasoning_service(db_session)


def _parse_text_context(raw: str | None) -> CompetitorTextContext:
    if raw is None or not raw.strip():
        return CompetitorTextContext()
    try:
        return CompetitorTextContext.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "text_context must be valid CompetitorTextContext JSON.",
                "errors": exc.errors(),
            },
        ) from exc


def _job_response(job) -> ClaudeReasoningJobResponse:
    return ClaudeReasoningJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude/reasoning/{job.id}",
        model_name=job.model_name,
        celery_task_id=job.celery_task_id,
        vision_result=job.vision_result,
        reasoning_result=job.reasoning_result,
        result=job.final_result,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.post(
    "/analyze",
    response_model=ClaudeReasoningEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue Claude 4.7 Vision + Chain-of-Thought analysis",
)
async def enqueue_competitor_analysis(
    images: Annotated[
        list[UploadFile],
        File(description="Competitor card images (1–5 JPEG/PNG/WebP)"),
    ],
    text_context: Annotated[
        str | None,
        Form(
            description=(
                "JSON CompetitorTextContext: title, description, characteristics, "
                "reviews_positive, reviews_negative, prices, marketplace, product_category"
            ),
        ),
    ] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: ClaudeReasoningService = Depends(_get_service),
) -> ClaudeReasoningEnqueueResponse:
    """Accept images + text, return task_id; CoT runs in Celery/Redis queue."""

    if not images:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one image file is required.",
        )

    payloads: list[bytes] = []
    try:
        for upload in images:
            payloads.append(await upload.read())
    finally:
        for upload in images:
            await upload.close()

    context = _parse_text_context(text_context)

    try:
        job, replay = await service.enqueue_analysis(
            user_id=current_user.id,
            images=tuple(payloads),
            text_context=context,
            idempotency_key=idempotency_key,
        )
    except ClaudeReasoningValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except S3StorageConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except S3StorageError as exc:
        logger.exception("S3 upload failed for Claude reasoning")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to store competitor images.",
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "claude.run_chain_of_thought",
            args=[str(job.id)],
            queue="claude.reasoning",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return ClaudeReasoningEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude/reasoning/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
    )


@router.get(
    "/{task_id}",
    response_model=ClaudeReasoningJobResponse,
    summary="Poll Claude reasoning job status / structured result",
)
async def get_reasoning_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ClaudeReasoningService = Depends(_get_service),
) -> ClaudeReasoningJobResponse:
    """Return Vision/CoT progress and final JSON when completed."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except ClaudeReasoningNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _job_response(job)
