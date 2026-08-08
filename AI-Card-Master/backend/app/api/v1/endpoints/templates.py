"""REST API: public template catalog + authenticated user designs.

Routes
------
Public presets
  GET  /api/v1/templates
  GET  /api/v1/templates/{template_id}
  POST /api/v1/templates/prompt-to-json

User designs (auth required)
  POST /api/v1/designs
  GET  /api/v1/designs
  POST /api/v1/designs/{design_id}/render
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.template_service import (
    TemplateNotFoundError,
    TemplateRenderError,
    TemplateService,
    TemplateStorageError,
    TemplateValidationError,
)
from app.core.config import get_settings
from app.infrastructure.persistence.template_repository import TemplateRepository
from app.models.database import get_db_session
from app.models.user import User
from app.schemas.templates import (
    CanvasStateDTO,
    DesignRenderRequest,
    DesignRenderResponse,
    SaveDesignRequest,
    SavedDesignDTO,
    SavedDesignListResponse,
    TemplateDetailDTO,
    TemplateListResponse,
    TemplateSummaryDTO,
)
from app.services.s3_storage import (
    S3StorageConfigurationError,
    S3StorageError,
    get_s3_storage,
)
from app.services.templates.prompt_parser import (
    CanvasPromptParserConfigurationError,
    CanvasPromptParserUpstreamError,
    CanvasPromptParserValidationError,
    get_canvas_prompt_parser,
)
from app.services.templates.renderer import get_canvas_server_renderer

logger = logging.getLogger(__name__)

templates_router = APIRouter(prefix="/api/v1/templates", tags=["templates"])
designs_router = APIRouter(prefix="/api/v1/designs", tags=["designs"])


def _map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TemplateNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TemplateValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, TemplateStorageError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, TemplateRenderError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    logger.exception("Unexpected template service failure")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Template request failed.",
    )


def _parse_canvas(raw: dict) -> CanvasStateDTO:
    try:
        return CanvasStateDTO.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stored canvas JSON is invalid: {exc.errors()}",
        ) from exc


async def get_template_service(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TemplateService:
    """Request-scoped template / design use-case service."""

    settings = get_settings()
    storage = None
    try:
        storage = get_s3_storage()
    except S3StorageConfigurationError:
        logger.debug("S3 not configured; design render will return 503 until set.")
    except S3StorageError:
        logger.warning("S3 client init failed", exc_info=True)

    return TemplateService(
        TemplateRepository(db_session),
        storage=storage,
        renderer=get_canvas_server_renderer(),
        presign_ttl_seconds=settings.s3_presign_ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Prompt → canvas JSON
# ---------------------------------------------------------------------------


class PromptToJsonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(..., min_length=1, max_length=8000)
    base_canvas: CanvasStateDTO | None = Field(
        default=None,
        description="Optional existing canvas to edit instead of creating fresh.",
    )


@templates_router.post(
    "/prompt-to-json",
    response_model=CanvasStateDTO,
    status_code=status.HTTP_200_OK,
    summary="Natural-language prompt → CanvasStateDTO",
    description=(
        "Uses the canvas prompt LLM parser to convert a free-form instruction "
        "into a validated ``CanvasStateDTO`` document for the editor."
    ),
)
async def prompt_to_json(
    body: PromptToJsonRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CanvasStateDTO:
    del current_user  # auth gate only
    parser = get_canvas_prompt_parser()
    try:
        return await parser.parse(body.prompt, base_canvas=body.base_canvas)
    except CanvasPromptParserValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except CanvasPromptParserConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CanvasPromptParserUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Public templates
# ---------------------------------------------------------------------------


@templates_router.get(
    "",
    response_model=TemplateListResponse,
    summary="List public template presets",
    description=(
        "Returns ready-made card presets with optional category filter and "
        "offset pagination (page / page_size)."
    ),
)
async def list_templates(
    service: Annotated[TemplateService, Depends(get_template_service)],
    category: Annotated[
        str | None,
        Query(max_length=64, description="Filter by template category"),
    ] = None,
    page: Annotated[int, Query(ge=1, description="1-based page index")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100, description="Items per page"),
    ] = 20,
) -> TemplateListResponse:
    try:
        result = await service.list_presets(
            category=category,
            page=page,
            page_size=page_size,
        )
    except TemplateValidationError as exc:
        raise _map_service_error(exc) from exc

    items = [
        TemplateSummaryDTO(
            id=item.id,
            title=item.title,
            category=item.category,
            preview_url=item.preview_url,
            downloads_count=item.downloads_count,
            created_at=item.created_at.isoformat(),
        )
        for item in result.items
    ]
    return TemplateListResponse(
        items=items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=(result.page * result.page_size) < result.total,
    )


@templates_router.get(
    "/{template_id}",
    response_model=TemplateDetailDTO,
    summary="Get full template canvas JSON",
)
async def get_template(
    template_id: UUID,
    service: Annotated[TemplateService, Depends(get_template_service)],
    track_download: Annotated[
        bool,
        Query(description="Increment downloads_count when true"),
    ] = False,
) -> TemplateDetailDTO:
    try:
        preset = await service.get_preset(
            template_id,
            track_download=track_download,
        )
        canvas = _parse_canvas(preset.canvas_data)
    except (TemplateNotFoundError, TemplateValidationError) as exc:
        raise _map_service_error(exc) from exc

    return TemplateDetailDTO(
        id=preset.id,
        title=preset.title,
        category=preset.category,
        is_preset=preset.is_preset,
        author_id=preset.author_id,
        canvas=canvas,
        preview_url=preset.preview_url,
        downloads_count=preset.downloads_count,
        created_at=preset.created_at.isoformat(),
        updated_at=preset.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# User designs
# ---------------------------------------------------------------------------


@designs_router.post(
    "",
    response_model=SavedDesignDTO,
    status_code=status.HTTP_200_OK,
    summary="Save or update a user design",
    description=(
        "Accepts a ``CanvasStateDTO`` payload. Provide ``id`` to update an "
        "existing project owned by the caller; omit to create a new one."
    ),
)
async def save_design(
    body: SaveDesignRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TemplateService, Depends(get_template_service)],
) -> SavedDesignDTO:
    try:
        design = await service.save_design(
            user_id=current_user.id,
            title=body.title,
            canvas=body.canvas,
            design_id=body.id,
            template_id=body.template_id,
            preview_url=body.preview_url,
        )
    except (
        TemplateNotFoundError,
        TemplateValidationError,
    ) as exc:
        raise _map_service_error(exc) from exc

    return SavedDesignDTO(
        id=design.id,
        title=design.title,
        template_id=design.template_id,
        canvas=_parse_canvas(design.canvas_data),
        preview_url=design.preview_url,
        updated_at=design.updated_at.isoformat(),
    )


@designs_router.get(
    "",
    response_model=SavedDesignListResponse,
    summary="List current user's designs",
)
async def list_designs(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TemplateService, Depends(get_template_service)],
) -> SavedDesignListResponse:
    designs = await service.list_designs(user_id=current_user.id)
    items = [
        SavedDesignDTO(
            id=design.id,
            title=design.title,
            template_id=design.template_id,
            canvas=_parse_canvas(design.canvas_data),
            preview_url=design.preview_url,
            updated_at=design.updated_at.isoformat(),
        )
        for design in designs
    ]
    return SavedDesignListResponse(items=items, total=len(items))


@designs_router.post(
    "/{design_id}/render",
    response_model=DesignRenderResponse,
    summary="Render design to HD card (Presigned S3 URL)",
    description=(
        "Composites the saved ``CanvasStateDTO`` server-side (Pillow) at high "
        "resolution and uploads the result to Selectel S3. Returns a temporary "
        "presigned download URL."
    ),
)
async def render_design(
    design_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TemplateService, Depends(get_template_service)],
    body: DesignRenderRequest | None = None,
) -> DesignRenderResponse:
    fmt: Literal["png", "webp"] = (body.output_format if body else "png")
    try:
        result = await service.render_design(
            user_id=current_user.id,
            design_id=design_id,
            output_format=fmt,
        )
    except (
        TemplateNotFoundError,
        TemplateValidationError,
        TemplateStorageError,
        TemplateRenderError,
    ) as exc:
        raise _map_service_error(exc) from exc

    mime: Literal["image/png", "image/webp"] = (
        "image/png" if result.mime_type == "image/png" else "image/webp"
    )
    return DesignRenderResponse(
        design_id=result.design_id,
        object_key=result.object_key,
        presigned_url=result.presigned_url,
        width=result.width,
        height=result.height,
        mime_type=mime,
        size_bytes=result.size_bytes,
        expires_in_seconds=result.expires_in_seconds,
    )
