"""Image upload API router.

Preserves the original upload contract from main.py and keeps the endpoint
under /api/v1/images for frontend (Next.js / Flutter) clients.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/images", tags=["images"])

# Absolute path to the directory where uploaded files will be stored.
UPLOADS_DIR = Path(__file__).resolve().parents[2] / "storage" / "uploads"

# Max accepted upload size in bytes (10 MB).
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Allowlist of supported MIME types and deterministic file extensions.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class UploadImageResponse(BaseModel):
    """Response schema for successful image upload."""

    success: bool = Field(..., description="Operation success flag")
    file_id: str = Field(..., description="Server-side unique file identifier")
    original_filename: str = Field(..., description="Original client filename")
    stored_filename: str = Field(..., description="Stored filename on the server")
    content_type: str = Field(..., description="Detected MIME type")
    size_bytes: int = Field(..., description="Stored file size in bytes")
    location: str = Field(..., description="Absolute storage path")
    public_path: str = Field(
        ...,
        description="Relative API path for referencing the uploaded asset",
    )


def _remove_partial_file(file_path: Path) -> None:
    """Best-effort cleanup for partially written files."""

    try:
        if file_path.exists():
            file_path.unlink()
    except OSError as cleanup_error:
        logger.warning("Failed to remove partial file %s: %s", file_path, cleanup_error)


def ensure_uploads_dir() -> Path:
    """Create and validate the uploads directory (used by app lifespan)."""

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    probe_file = UPLOADS_DIR / ".write_probe"
    probe_file.write_text("ok", encoding="utf-8")
    probe_file.unlink(missing_ok=True)
    return UPLOADS_DIR


@router.post(
    "/upload",
    response_model=UploadImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload product image",
    description=(
        "Accepts a single product image (JPEG / PNG / WebP, max 10 MB) "
        "and stores it for downstream AI card generation."
    ),
)
async def upload_image(file: UploadFile = File(..., description="Product image file")) -> UploadImageResponse:
    """Upload a single image file.

    Validation steps:
    1) Ensure file metadata exists.
    2) Validate MIME type against allowlist.
    3) Stream file to disk with hard size cap.
    4) Return deterministic upload metadata.
    """

    file_uuid = uuid4().hex
    stored_file_path: Path | None = None
    total_size = 0

    try:
        if not file.filename or not file.filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required.",
            )

        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Unsupported image type. Allowed types: "
                    f"{', '.join(sorted(ALLOWED_IMAGE_TYPES))}."
                ),
            )

        extension = ALLOWED_IMAGE_TYPES[file.content_type]
        stored_filename = f"{file_uuid}{extension}"
        stored_file_path = UPLOADS_DIR / stored_filename

        with stored_file_path.open("wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break

                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "File is too large. Maximum allowed size is "
                            f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
                        ),
                    )

                buffer.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        return UploadImageResponse(
            success=True,
            file_id=file_uuid,
            original_filename=file.filename,
            stored_filename=stored_filename,
            content_type=file.content_type,
            size_bytes=total_size,
            location=str(stored_file_path.resolve()),
            public_path=f"/api/v1/images/files/{stored_filename}",
        )

    except HTTPException:
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise
    except OSError as io_error:
        logger.exception("I/O error during upload: %s", io_error)
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist uploaded file.",
        ) from io_error
    except Exception as unexpected_error:
        logger.exception("Unexpected upload error: %s", unexpected_error)
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during file upload.",
        ) from unexpected_error
    finally:
        try:
            await file.close()
        except Exception as close_error:
            logger.warning("Failed to close upload stream: %s", close_error)
