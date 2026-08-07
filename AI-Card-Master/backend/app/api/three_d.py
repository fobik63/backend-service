"""HTTP API for 3D generation enqueue, assets, GPU rental stubs, and webhooks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.images import ALLOWED_IMAGE_TYPES, UPLOADS_DIR, ensure_uploads_dir
from app.api.payments import get_current_user
from app.application.three_d_service import (
    ThreeDNotFoundError,
    ThreeDValidationError,
    parse_webhook_json,
)
from app.core.rate_limit import three_d_generate_limit
from app.domain.three_d import (
    GpuRentalSessionView,
    ThreeDAssetView,
    ThreeDPresignedUrls,
    ThreeDTaskStatus,
    ThreeDTaskView,
)
from app.infrastructure.celery_app import CELERY_THREE_D_HEAVY_QUEUE, celery_app
from app.infrastructure.three_d_factory import build_three_d_service
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.three_d.errors import (
    THREE_D_UNAVAILABLE_MESSAGE,
    ThreeDServiceUnavailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/3d", tags=["3D Generation"])
MAX_WEBHOOK_BYTES = 1024 * 1024
MAX_GENERATE_IMAGE_BYTES = 10 * 1024 * 1024
_QUEUED_STATUS = "QUEUED"


class CreateThreeDTaskRequest(BaseModel):
    """JSON body for ``POST /generate`` (and legacy ``POST /tasks``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str | None = Field(default=None, max_length=4000)
    image: str | None = Field(
        default=None,
        max_length=2048,
        description="Optional source image URL (JSON). FormData uses the image file.",
    )
    source_image_url: str | None = Field(default=None, max_length=2048)
    mode: Literal["draft", "standard", "hd"] | None = Field(
        default="standard",
        description="Quality tier: draft=10, standard=30, hd=60 base coins.",
    )
    model: str | None = Field(
        default=None,
        max_length=64,
        description="Optional provider/model id for pricing coefficients.",
    )
    polycount_limit: int | None = Field(default=None, ge=100, le=2_000_000)
    polycount_target: int | None = Field(default=None, ge=100, le=2_000_000)
    format: Literal["GLB", "USDZ", "glb", "usdz"] | None = Field(default="GLB")
    texture_resolution: int | None = Field(default=None, ge=256, le=8192)

    @field_validator("format", mode="before")
    @classmethod
    def _normalise_format(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("mode", mode="before")
    @classmethod
    def _normalise_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ThreeDTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID
    status: str
    input_type: str
    prompt: str | None = None
    source_image_url: str | None = None
    provider_name: str | None = None
    provider_job_id: str | None = None
    cost_coins: int
    progress_percent: int
    stage: str | None = None
    stage_label: str | None = None
    output_format: str | None = None
    celery_task_id: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class GenerateThreeDResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: UUID
    status: str = _QUEUED_STATUS
    status_url: str
    celery_task_id: str | None = None
    cost_coins: int
    idempotent_replay: bool = False


class CreateThreeDTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: ThreeDTaskResponse
    celery_task_id: str | None = None
    idempotent_replay: bool = False


class ThreeDAssetItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID
    task_id: UUID
    file_glb_url: str | None = None
    file_usdz_url: str | None = None
    file_obj_url: str | None = None
    preview_png_url: str | None = None
    thumbnail_url: str | None = None
    polycount_actual: int | None = None
    file_size_bytes: int | None = None


class ThreeDAssetsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[ThreeDAssetItemResponse]
    total: int
    limit: int
    offset: int


class GpuRentalStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instance_type: str | None = Field(default=None, max_length=128)


class GpuRentalSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: UUID
    status: str
    provider_name: str
    instance_type: str
    coins_per_minute: int
    hourly_rate_coins: int
    started_at: str | None = None
    stopped_at: str | None = None
    total_cost_coins: int


class GpuRentalStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: UUID


class WebhookAck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    success: bool = True
    accepted: bool = True
    already_processed: bool = False
    task_id: UUID | None = None
    status: str | None = None


def get_three_d_svc(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
):
    return build_three_d_service(db_session)


def _api_status(task: ThreeDTaskView) -> str:
    """Map persisted PENDING onto the public QUEUED lifecycle label."""

    if task.status is ThreeDTaskStatus.PENDING:
        return _QUEUED_STATUS
    return task.status.value


def _to_response(task: ThreeDTaskView) -> ThreeDTaskResponse:
    from app.domain.three_d import stage_label

    return ThreeDTaskResponse(
        id=task.id,
        status=_api_status(task),
        input_type=task.input_type.value,
        prompt=task.prompt,
        source_image_url=task.source_image_url,
        provider_name=task.provider_name,
        provider_job_id=task.provider_job_id,
        cost_coins=task.cost_coins,
        progress_percent=task.progress_percent,
        stage=task.stage,
        stage_label=stage_label(task.stage),
        output_format=task.output_format.value if task.output_format else None,
        celery_task_id=task.celery_task_id,
        error_message=task.error_message,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


def _to_asset_item(
    asset: ThreeDAssetView, urls: ThreeDPresignedUrls
) -> ThreeDAssetItemResponse:
    return ThreeDAssetItemResponse(
        id=asset.id,
        task_id=asset.task_id,
        file_glb_url=urls.glb,
        file_usdz_url=urls.usdz,
        file_obj_url=urls.obj,
        preview_png_url=urls.preview_png,
        thumbnail_url=urls.thumbnail,
        polycount_actual=asset.polycount_actual,
        file_size_bytes=asset.file_size_bytes,
    )


def _to_gpu_response(session: GpuRentalSessionView) -> GpuRentalSessionResponse:
    coins_per_minute = max(0, int(session.hourly_rate_coins) // 60)
    return GpuRentalSessionResponse(
        session_id=session.id,
        status=session.status.value,
        provider_name=session.provider_name,
        instance_type=session.instance_type,
        coins_per_minute=coins_per_minute,
        hourly_rate_coins=session.hourly_rate_coins,
        started_at=session.started_at.isoformat() if session.started_at else None,
        stopped_at=session.stopped_at.isoformat() if session.stopped_at else None,
        total_cost_coins=session.total_cost_coins,
    )


async def _store_generate_image(upload: UploadFile) -> str:
    """Persist an optional FormData image and return a public reference path."""

    content_type = (upload.content_type or "").strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Unsupported image type. Allowed types: "
                f"{', '.join(sorted(ALLOWED_IMAGE_TYPES))}."
            ),
        )
    ensure_uploads_dir()
    extension = ALLOWED_IMAGE_TYPES[content_type]
    stored_filename = f"{uuid4().hex}{extension}"
    stored_path = UPLOADS_DIR / stored_filename
    total = 0
    try:
        with stored_path.open("wb") as buffer:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_GENERATE_IMAGE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Image exceeds the 10 MB limit.",
                    )
                buffer.write(chunk)
    except HTTPException:
        _safe_unlink(stored_path)
        raise
    except Exception:
        _safe_unlink(stored_path)
        raise
    finally:
        await upload.close()
    return f"/api/v1/images/files/{stored_filename}"


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Failed to remove partial 3D upload %s", path, exc_info=True)


async def _enqueue_generation(
    *,
    service: Any,
    current_user: User,
    prompt: str | None,
    source_image_url: str | None,
    polycount_limit: int | None,
    output_format: str | None,
    texture_resolution: int | None,
    idempotency_key: str | None,
    mode: str | None = "standard",
    model: str | None = None,
) -> tuple[ThreeDTaskView, str | None, bool]:
    try:
        await service.ensure_engine_available()
        task, replay = await service.create_task(
            user_id=current_user.id,
            prompt=prompt,
            source_image_url=source_image_url,
            ai_coins=int(current_user.ai_coins),
            polycount_target=polycount_limit,
            texture_resolution=texture_resolution,
            output_format=output_format,
            idempotency_key=idempotency_key,
            mode=mode,
            model=model,
        )
    except ThreeDServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc) or THREE_D_UNAVAILABLE_MESSAGE,
        ) from exc
    except ThreeDValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc

    celery_task_id = task.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "three_d.process_generation_task",
            args=[str(task.id)],
            queue=CELERY_THREE_D_HEAVY_QUEUE,
        )
        celery_task_id = async_result.id
        task = await service.attach_celery_task(
            task_id=task.id,
            celery_task_id=celery_task_id,
        )
    return task, celery_task_id, replay


@router.post(
    "/generate",
    response_model=GenerateThreeDResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a 3D generation task",
)
@three_d_generate_limit
async def generate_three_d(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> GenerateThreeDResponse:
    """Accept JSON or FormData, reserve coins, enqueue Celery, return QUEUED."""

    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        resolved_prompt = _form_str(form.get("prompt"))
        resolved_polycount = _form_optional_int(form.get("polycount_limit"))
        if resolved_polycount is None:
            resolved_polycount = _form_optional_int(form.get("polycount_target"))
        resolved_format = (_form_str(form.get("format")) or "GLB").upper()
        resolved_texture = _form_optional_int(form.get("texture_resolution"))
        resolved_mode = (_form_str(form.get("mode")) or "standard").lower()
        resolved_model = _form_str(form.get("model"))
        resolved_image_url = _form_str(form.get("source_image_url")) or _form_str(
            form.get("image_url")
        )
        image_field = form.get("image")
        if hasattr(image_field, "filename") and getattr(image_field, "filename", None):
            resolved_image_url = await _store_generate_image(image_field)  # type: ignore[arg-type]
    else:
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Expected application/json or multipart/form-data body.",
            ) from exc
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="JSON body must be an object.",
            )
        try:
            body = CreateThreeDTaskRequest.model_validate(raw)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        resolved_prompt = body.prompt
        resolved_image_url = body.image or body.source_image_url
        resolved_polycount = body.polycount_limit or body.polycount_target
        resolved_format = body.format or "GLB"
        resolved_texture = body.texture_resolution
        resolved_mode = body.mode or "standard"
        resolved_model = body.model

    if idempotency_key:
        idempotency_key = idempotency_key.strip()

    task, celery_task_id, replay = await _enqueue_generation(
        service=service,
        current_user=current_user,
        prompt=resolved_prompt,
        source_image_url=resolved_image_url,
        polycount_limit=resolved_polycount,
        output_format=resolved_format,
        texture_resolution=resolved_texture,
        idempotency_key=idempotency_key,
        mode=resolved_mode,
        model=resolved_model,
    )
    return GenerateThreeDResponse(
        task_id=task.id,
        status=_QUEUED_STATUS
        if task.status is ThreeDTaskStatus.PENDING
        else _api_status(task),
        status_url=f"/api/v1/3d/tasks/{task.id}",
        celery_task_id=celery_task_id,
        cost_coins=task.cost_coins,
        idempotent_replay=replay,
    )


def _form_str(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "filename"):
        return None
    text = str(value).strip()
    return text or None


def _form_optional_int(value: Any) -> int | None:
    text = _form_str(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid integer form field: {text!r}",
        ) from exc


@router.post(
    "/tasks",
    response_model=CreateThreeDTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Legacy alias for POST /generate (JSON body)",
    include_in_schema=False,
)
@three_d_generate_limit
async def create_three_d_task(
    request: Request,
    body: CreateThreeDTaskRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> CreateThreeDTaskResponse:
    """Backward-compatible JSON enqueue endpoint."""

    _ = request  # required by slowapi
    if idempotency_key:
        idempotency_key = idempotency_key.strip()
    task, celery_task_id, replay = await _enqueue_generation(
        service=service,
        current_user=current_user,
        prompt=body.prompt,
        source_image_url=body.image or body.source_image_url,
        polycount_limit=body.polycount_limit or body.polycount_target,
        output_format=body.format or "GLB",
        texture_resolution=body.texture_resolution,
        idempotency_key=idempotency_key,
        mode=body.mode or "standard",
        model=body.model,
    )
    return CreateThreeDTaskResponse(
        task=_to_response(task),
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
    )


@router.get("/tasks/{task_id}", response_model=ThreeDTaskResponse)
async def get_three_d_task(
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
) -> ThreeDTaskResponse:
    try:
        task = await service.get_for_user(task_id=task_id, user_id=current_user.id)
    except ThreeDNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _to_response(task)


@router.get("/assets", response_model=ThreeDAssetsListResponse)
async def list_three_d_assets(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ThreeDAssetsListResponse:
    """Paginated list of the current user's completed 3D models."""

    items, total = await service.list_assets_for_user(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return ThreeDAssetsListResponse(
        items=[_to_asset_item(asset, urls) for asset, urls in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/gpu-rental/start",
    response_model=GpuRentalSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a GPU rental session (stub)",
)
async def start_gpu_rental(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
    body: GpuRentalStartRequest | None = None,
) -> GpuRentalSessionResponse:
    """Reserve a GPU node; coins are billed per minute when the session stops."""

    try:
        session = await service.start_gpu_rental(
            user_id=current_user.id,
            ai_coins=int(current_user.ai_coins),
            instance_type=body.instance_type if body else None,
        )
    except ThreeDValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    return _to_gpu_response(session)


@router.post(
    "/gpu-rental/stop",
    response_model=GpuRentalSessionResponse,
    summary="Stop a GPU rental session (stub)",
)
async def stop_gpu_rental(
    body: GpuRentalStopRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[Any, Depends(get_three_d_svc)],
) -> GpuRentalSessionResponse:
    """Stop the GPU node and debit coins for elapsed billed minutes."""

    try:
        session = await service.stop_gpu_rental(
            user_id=current_user.id,
            session_id=body.session_id,
        )
    except ThreeDNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    return _to_gpu_response(session)


@router.post("/webhook/{provider_name}", response_model=WebhookAck)
async def receive_three_d_webhook(
    provider_name: str,
    request: Request,
    service: Annotated[Any, Depends(get_three_d_svc)],
    callback_token: Annotated[str | None, Query(alias="token", max_length=512)] = None,
    content_length: Annotated[int | None, Header(alias="Content-Length", ge=0)] = None,
) -> WebhookAck:
    """HMAC-validated callback from external GPU nodes / 3D APIs."""

    if content_length is not None and content_length > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload is too large.",
        )
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload is too large.",
        )
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not service.verify_webhook_signature(
        headers=headers,
        raw_body=raw_body,
        callback_token=callback_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = parse_webhook_json(raw_body)
        task, already = await service.accept_webhook(
            provider_name=provider_name,
            payload=payload,
        )
    except ThreeDValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ThreeDNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return WebhookAck(
        already_processed=already,
        task_id=task.id,
        status=task.status.value,
    )
