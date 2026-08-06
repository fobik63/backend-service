"""Claude analyses API aliases at /api/v1/claude-analyses (plan contract)."""

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
from app.domain.bulk_generation import detect_image_mime
from app.domain.claude_reasoning import (
    ClaudeReasoningJobStatus,
    CompetitorTextContext,
)
from app.infrastructure.claude.image_normalize import normalize_image_for_claude
from app.infrastructure.claude_reasoning_factory import build_claude_reasoning_service
from app.models.database import get_db_session
from app.models.user import User
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/claude-analyses", tags=["claude-analyses"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClaudeAnalysisCreateResponse(StrictAPIModel):
    analysis_id: UUID
    status: ClaudeReasoningJobStatus
    status_url: str
    progress: int = Field(ge=0, le=100)
    idempotent_replay: bool = False


class ClaudeAnalysisStatusResponse(StrictAPIModel):
    analysis_id: UUID
    status: ClaudeReasoningJobStatus
    status_url: str
    progress: int = Field(ge=0, le=100)
    model_name: str
    result: dict[str, Any] | None = None
    vision_result: dict[str, Any] | None = None
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


def _parse_context_json(raw: str | None) -> CompetitorTextContext:
    if raw is None or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="context_json is required and must be CompetitorTextContext JSON.",
        )
    try:
        return CompetitorTextContext.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "context_json must be valid CompetitorTextContext JSON.",
                "errors": exc.errors(),
            },
        ) from exc


def _status_response(job) -> ClaudeAnalysisStatusResponse:
    return ClaudeAnalysisStatusResponse(
        analysis_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude-analyses/{job.id}",
        progress=job.progress,
        model_name=job.model_name,
        result=job.final_result,
        vision_result=job.vision_result,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.post(
    "",
    response_model=ClaudeAnalysisCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue Claude 4.7 Vision + text-correlation analysis",
)
async def create_claude_analysis(
    images: Annotated[
        list[UploadFile],
        File(description="Competitor card images (1–5 JPEG/PNG/WebP)"),
    ],
    context_json: Annotated[
        str,
        Form(
            description=(
                "JSON CompetitorTextContext including image_contexts "
                "(one entry per uploaded image), plus title/description/"
                "characteristics/reviews/prices/marketplace/product_category"
            ),
        ),
    ],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
    current_user: User = Depends(get_current_user),
    service: ClaudeReasoningService = Depends(_get_service),
) -> ClaudeAnalysisCreateResponse:
    """Accept images + text, persist privately, enqueue via transactional outbox."""

    if not images:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one image file is required.",
        )

    payloads: list[bytes] = []
    try:
        for upload in images:
            raw = await upload.read()
            detected = detect_image_mime(raw)
            if detected is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Each image must be a valid JPEG, PNG, or WebP file.",
                )
            mime_type, _ext = detected
            normalized, _media = normalize_image_for_claude(raw, media_type=mime_type)
            payloads.append(normalized)
    finally:
        for upload in images:
            await upload.close()

    context = _parse_context_json(context_json)
    if len(context.image_contexts) != len(payloads):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "context_json.image_contexts must contain one entry per uploaded image."
            ),
        )

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
        logger.exception("S3 upload failed for Claude analysis")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to store competitor images.",
        ) from exc

    return ClaudeAnalysisCreateResponse(
        analysis_id=job.id,
        status=job.status,
        status_url=f"/api/v1/claude-analyses/{job.id}",
        progress=job.progress,
        idempotent_replay=replay,
    )


@router.get(
    "/{analysis_id}",
    response_model=ClaudeAnalysisStatusResponse,
    summary="Poll Claude analysis status / structured result",
)
async def get_claude_analysis(
    analysis_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ClaudeReasoningService = Depends(_get_service),
) -> ClaudeAnalysisStatusResponse:
    """Return owner-scoped PostgreSQL status and typed JSON result."""

    try:
        job = await service.get_job_for_user(
            user_id=current_user.id,
            job_id=analysis_id,
        )
    except ClaudeReasoningNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _status_response(job)
