"""Generation HTTP controller: receive → validate → pipeline → respond."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.captcha import enforce_generation_behavioral_limit
from app.api.dependencies.auth import get_current_user
from app.application.generation_cabinet_service import GenerationCabinetService
from app.application.generation_errors import (
    GenerationForbiddenError,
    GenerationSubmissionError,
)
from app.application.generation_options import (
    effective_engine_mode as _effective_engine_mode,
    ensure_generation_options_allowed,
    validate_owned_source_object_key,
)
from app.core.config import get_settings
from app.core.rate_limit import generations_user_limit
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.domain.silent_ban import pick_shadow_delay_seconds
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.database import get_db_session
from app.models.user import User
from app.schemas.generations import (
    GenerationCreateResponse,
    GenerationForm,
    GenerationHistoryItemResponse,
    GenerationStatusResponse,
    ModelModeRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/generations", tags=["generations"])


def get_generation_cabinet_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> GenerationCabinetService:
    return GenerationCabinetService(
        GenerationRepository(db_session),
        db_session,
    )


def _map_generation_error(exc: GenerationSubmissionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _validate_owned_source_object_key(object_key: str, user_id: UUID) -> None:
    try:
        validate_owned_source_object_key(object_key, user_id)
    except GenerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc


def _ensure_engine_mode_allowed(engine_mode: GenerationEngineMode, user: User) -> None:
    try:
        ensure_generation_options_allowed(
            engine_mode,
            GenerationPostProcessingMode.FAST,
            user,
        )
    except GenerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc


def _ensure_generation_options_allowed(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
    user: User,
) -> None:
    try:
        ensure_generation_options_allowed(engine_mode, post_processing_mode, user)
    except GenerationForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc


def _archive_retention():
    return GenerationCabinetService._archive_retention()


async def _maybe_emulate_flagged_http_timeout(user: User) -> None:
    """Optional silent-ban path: inflate latency then look like a gateway timeout."""

    settings = get_settings()
    if not settings.silent_ban_enabled or not settings.silent_ban_emulate_http_timeout:
        return
    if not bool(getattr(user, "is_flagged", False)):
        return
    delay = pick_shadow_delay_seconds(
        min_seconds=settings.silent_ban_shadow_delay_min_seconds,
        max_seconds=settings.silent_ban_shadow_delay_max_seconds,
    )
    logger.info(
        "Silent-ban HTTP timeout emulation delay=%ss user_id=%s",
        delay,
        user.id,
    )
    await asyncio.sleep(delay)
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail="Upstream provider timed out while loading. Please try again.",
    )


async def _read_upload_bytes(file: UploadFile, *, max_bytes: int) -> bytes:
    """HTTP-layer bounded read; content validation lives in the service."""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "generation_payload_too_large",
                    "message": f"Image exceeds the {max_bytes}-byte upload limit.",
                },
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "generation_bad_request",
                "message": "Uploaded image is empty.",
            },
        )
    return b"".join(chunks)


async def parse_generation_form(
    product_category: Annotated[str | None, Form(max_length=128)] = None,
    engine_mode: Annotated[GenerationEngineMode, Form()] = GenerationEngineMode.STANDARD,
    post_processing_mode: Annotated[
        GenerationPostProcessingMode,
        Form(),
    ] = GenerationPostProcessingMode.FAST,
    apply_text_overlays: Annotated[bool, Form()] = False,
    overlay_texts: Annotated[str | None, Form(max_length=3000)] = None,
    preserve_subject: Annotated[bool, Form()] = True,
    editor_cover_only: Annotated[bool, Form()] = False,
    style_prompt: Annotated[str | None, Form(max_length=2000)] = None,
) -> GenerationForm:
    parsed_overlays: dict[str, str] = {}
    if overlay_texts:
        try:
            raw = json.loads(overlay_texts)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "generation_validation_error",
                    "message": "overlay_texts must be a JSON object.",
                },
            ) from exc
        if not isinstance(raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "generation_validation_error",
                    "message": "overlay_texts must map slide names to strings.",
                },
            )
        parsed_overlays = raw
    try:
        return GenerationForm(
            product_category=product_category,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            apply_text_overlays=apply_text_overlays,
            overlay_texts=parsed_overlays,
            preserve_subject=preserve_subject,
            editor_cover_only=editor_cover_only,
            style_prompt=style_prompt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "generation_validation_error",
                "message": str(exc),
            },
        ) from exc


@router.post(
    "/model",
    response_model=GenerationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create AI Model virtual try-on generation",
)
@generations_user_limit
async def create_model_generation(
    request: Request,
    payload: ModelModeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    cabinet: Annotated[GenerationCabinetService, Depends(get_generation_cabinet_service)],
    _: Annotated[None, Depends(enforce_generation_behavioral_limit)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> GenerationCreateResponse:
    await _maybe_emulate_flagged_http_timeout(current_user)
    try:
        result = await cabinet.submit_model_mode(
            user=current_user,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        return result.to_response()
    except GenerationSubmissionError as exc:
        logger.warning(
            "Model generation rejected code=%s user_id=%s detail=%s",
            exc.code,
            current_user.id,
            exc.message,
        )
        raise _map_generation_error(exc) from exc


@router.post(
    "",
    response_model=GenerationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@generations_user_limit
async def create_generation(
    request: Request,
    file: Annotated[UploadFile, File(description="JPEG, PNG, or WebP product photo")],
    form: Annotated[GenerationForm, Depends(parse_generation_form)],
    current_user: Annotated[User, Depends(get_current_user)],
    cabinet: Annotated[GenerationCabinetService, Depends(get_generation_cabinet_service)],
    _: Annotated[None, Depends(enforce_generation_behavioral_limit)],
    mask_image: Annotated[
        UploadFile | None,
        File(description="Optional subject mask (white = product)"),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> GenerationCreateResponse:
    """Receive file → validate → pipeline → 202 Accepted."""

    await _maybe_emulate_flagged_http_timeout(current_user)
    settings = get_settings()
    mask_bytes: bytes | None = None
    try:
        image_bytes = await _read_upload_bytes(
            file, max_bytes=settings.generation_max_upload_bytes
        )
        if mask_image is not None and mask_image.filename:
            mask_bytes = await _read_upload_bytes(
                mask_image, max_bytes=settings.generation_max_upload_bytes
            )
        result = await cabinet.submit_from_upload(
            user=current_user,
            image_bytes=image_bytes,
            claimed_content_type=file.content_type,
            product_category=form.product_category,
            engine_mode=form.engine_mode,
            post_processing_mode=form.post_processing_mode,
            apply_text_overlays=form.apply_text_overlays,
            overlay_texts=form.overlay_texts,
            idempotency_key=idempotency_key,
            mask_bytes=mask_bytes,
            mask_content_type=(
                mask_image.content_type if mask_image is not None else None
            ),
            preserve_subject=form.preserve_subject,
            editor_cover_only=form.editor_cover_only,
            style_prompt=form.style_prompt,
        )
        return result.to_response()
    except GenerationSubmissionError as exc:
        logger.warning(
            "Generation rejected code=%s user_id=%s detail=%s",
            exc.code,
            current_user.id,
            exc.message,
        )
        raise _map_generation_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected generation submit failure user_id=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "generation_internal_error",
                "message": "Failed to create generation task.",
            },
        ) from exc
    finally:
        await file.close()
        if mask_image is not None:
            await mask_image.close()


@router.get("/history", response_model=list[GenerationHistoryItemResponse])
@generations_user_limit
async def list_generation_history(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GenerationHistoryItemResponse]:
    cabinet = GenerationCabinetService(GenerationRepository(db_session), db_session)
    try:
        return await cabinet.list_history(
            user_id=current_user.id, limit=limit, offset=offset
        )
    except GenerationSubmissionError as exc:
        raise _map_generation_error(exc) from exc
    except Exception as exc:
        logger.exception("Generation history failed user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "generation_internal_error",
                "message": "Failed to load generation history.",
            },
        ) from exc


@router.get("/{task_id}", response_model=GenerationStatusResponse)
@generations_user_limit
async def get_generation_status(
    request: Request,
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationStatusResponse:
    cabinet = GenerationCabinetService(GenerationRepository(db_session), db_session)
    try:
        return await cabinet.get_status(user_id=current_user.id, task_id=task_id)
    except GenerationSubmissionError as exc:
        raise _map_generation_error(exc) from exc
    except Exception as exc:
        logger.exception(
            "Generation status failed user_id=%s task_id=%s",
            current_user.id,
            task_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "generation_internal_error",
                "message": "Failed to load generation status.",
            },
        ) from exc
