"""Custom font upload API (TTF / OTF → custom_fonts registry)."""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.models.database import get_db_session
from app.models.user import User
from app.services.templates.font_manager import (
    FontManagerService,
    FontStorageError,
    FontValidationError,
    get_font_manager_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fonts", tags=["fonts"])

_MAX_READ_BYTES = 8 * 1024 * 1024


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UploadFontResponse(StrictAPIModel):
    """Response schema for a successful custom font upload."""

    success: bool = Field(default=True, description="Operation success flag")
    id: UUID = Field(..., description="custom_fonts row id")
    font_name: str = Field(..., min_length=1, max_length=128)
    font_family: str = Field(..., min_length=1, max_length=128)
    file_path_ttf: str = Field(..., min_length=1)
    file_path_woff2: str | None = Field(
        default=None,
        description="Optional S3 URI (s3://bucket/key) when cloud upload succeeded",
    )
    is_system: bool = False
    storage: Literal["s3", "local"] = Field(
        ...,
        description="Primary persistence backend used for this upload",
    )
    size_bytes: int = Field(..., ge=1)


class FontCatalogResponse(StrictAPIModel):
    fallback_family: str
    system_families: tuple[str, ...]
    known_families: tuple[str, ...]


def _get_font_manager() -> FontManagerService:
    return get_font_manager_service()


async def _read_bounded_font(file: UploadFile, *, max_bytes: int) -> bytes:
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
                detail=f"Font exceeds the {max_bytes}-byte upload limit.",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded font file is empty.",
        )
    return b"".join(chunks)


@router.get(
    "",
    response_model=FontCatalogResponse,
    summary="List known font families",
)
async def list_fonts(
    manager: Annotated[FontManagerService, Depends(_get_font_manager)],
) -> FontCatalogResponse:
    """Return default system families and currently registered family names."""

    from app.services.templates.font_manager import DEFAULT_SYSTEM_FAMILIES

    known = tuple(sorted(manager.known_families))
    return FontCatalogResponse(
        fallback_family=manager.fallback_family,
        system_families=DEFAULT_SYSTEM_FAMILIES,
        known_families=known,
    )


@router.post(
    "/upload",
    response_model=UploadFontResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a custom TTF/OTF font",
    description=(
        "Validates TrueType/OpenType signature and fontTools name-table metadata, "
        "stores the file in S3 (when configured) or local ``storage/fonts``, "
        "and inserts a ``custom_fonts`` row."
    ),
)
async def upload_font(
    file: Annotated[UploadFile, File(description="TrueType (.ttf) or OpenType (.otf) font")],
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    manager: Annotated[FontManagerService, Depends(_get_font_manager)],
) -> UploadFontResponse:
    """Upload and register a user font for canvas rendering."""

    _ = current_user  # auth gate; ownership column not on custom_fonts yet
    try:
        payload = await _read_bounded_font(file, max_bytes=_MAX_READ_BYTES)
        result = await manager.upload_font(
            session=db_session,
            data=payload,
            filename=file.filename,
            content_type=file.content_type,
        )
    except FontValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except FontStorageError as exc:
        logger.exception("Font storage failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()

    return UploadFontResponse(
        success=True,
        id=result.id,
        font_name=result.font_name,
        font_family=result.font_family,
        file_path_ttf=result.file_path_ttf,
        file_path_woff2=result.file_path_woff2,
        is_system=result.is_system,
        storage=result.storage,
        size_bytes=result.size_bytes,
    )
