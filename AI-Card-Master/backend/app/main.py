"""Main entrypoint for the AI-Card-Master FastAPI backend.

This module contains:
- app bootstrap and lifespan logic,
- global exception handlers,
- basic service endpoints,
- image upload endpoint with validation and safe persistence.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api import admin_router


# Configure module logger.
# In a production setup, centralized logging config should live in app/core.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# Absolute path to the directory where uploaded files will be stored.
# The directory is created safely on startup in the lifespan handler.
UPLOADS_DIR = Path(__file__).resolve().parents[1] / "storage" / "uploads"


# Max accepted upload size in bytes (10 MB).
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


# Allowlist of supported MIME types and deterministic file extensions.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class RootResponse(BaseModel):
    """Response schema for the root endpoint."""

    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    message: str = Field(..., description="Human-friendly welcome message")


class HealthResponse(BaseModel):
    """Response schema for health checks."""

    status: str = Field(..., description="Health status")
    detail: str = Field(..., description="Additional diagnostic detail")


class UploadImageResponse(BaseModel):
    """Response schema for successful image upload."""

    success: bool = Field(..., description="Operation success flag")
    file_id: str = Field(..., description="Server-side unique file identifier")
    original_filename: str = Field(..., description="Original client filename")
    stored_filename: str = Field(..., description="Stored filename on the server")
    content_type: str = Field(..., description="Detected MIME type")
    size_bytes: int = Field(..., description="Stored file size in bytes")
    location: str = Field(..., description="Absolute storage path")


def _remove_partial_file(file_path: Path) -> None:
    """Best-effort cleanup for partially written files.

    This helper is intentionally defensive:
    if deletion fails, we log the failure but do not raise a new exception
    because the original business error is more important for API clients.
    """

    try:
        if file_path.exists():
            file_path.unlink()
    except OSError as cleanup_error:
        logger.warning("Failed to remove partial file %s: %s", file_path, cleanup_error)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and validate runtime resources.

    For now we only ensure the upload directory exists and is writable.
    """

    try:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        # Optional writability probe to fail fast at startup.
        probe_file = UPLOADS_DIR / ".write_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)

        logger.info("Upload directory is ready: %s", UPLOADS_DIR)
    except OSError as startup_error:
        logger.exception("Startup failed: upload directory is not available")
        raise RuntimeError("Upload storage initialization failed") from startup_error

    yield


app = FastAPI(
    title="AI-Card-Master API",
    version="0.1.0",
    description="Backend API for AI-powered card/image workflows.",
    lifespan=lifespan,
)


# Register API routers.
app.include_router(admin_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Return consistent JSON for business and validation HTTP errors."""

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "detail": exc.detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return explicit details for request schema/shape validation errors."""

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "detail": "Request validation failed.",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch unexpected exceptions and prevent trace leaks to clients."""

    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "detail": "Internal server error.",
        },
    )


@app.get("/", response_model=RootResponse, tags=["system"])
async def root() -> RootResponse:
    """Basic root route.

    Helps quickly verify that the service is up and responding.
    """

    try:
        return RootResponse(
            service="AI-Card-Master API",
            version="0.1.0",
            message="Service is running. Use /api/v1/images/upload to upload images.",
        )
    except Exception as endpoint_error:
        logger.exception("Root endpoint failed: %s", endpoint_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve root endpoint.",
        ) from endpoint_error


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Simple health check endpoint."""

    try:
        return HealthResponse(status="ok", detail="Service and upload storage are ready.")
    except Exception as endpoint_error:
        logger.exception("Health endpoint failed: %s", endpoint_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check service health.",
        ) from endpoint_error


@app.post(
    "/api/v1/images/upload",
    response_model=UploadImageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["images"],
)
async def upload_image(file: UploadFile = File(...)) -> UploadImageResponse:
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
        # Validate filename presence. Some clients may omit filename entirely.
        if not file.filename or not file.filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required.",
            )

        # Validate MIME type before doing any heavy I/O.
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Unsupported image type. Allowed types: "
                    f"{', '.join(sorted(ALLOWED_IMAGE_TYPES))}."
                ),
            )

        # Use a generated filename to avoid path traversal and collisions.
        extension = ALLOWED_IMAGE_TYPES[file.content_type]
        stored_filename = f"{file_uuid}{extension}"
        stored_file_path = UPLOADS_DIR / stored_filename

        # Stream file in chunks to avoid loading the entire payload into memory.
        # This pattern also allows strict size limit enforcement while streaming.
        with stored_file_path.open("wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunk
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
        )

    except HTTPException:
        # If request fails for business reasons, cleanup partial content and re-raise.
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise
    except OSError as io_error:
        # Handle filesystem failures explicitly.
        logger.exception("I/O error during upload: %s", io_error)
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist uploaded file.",
        ) from io_error
    except Exception as unexpected_error:
        # Catch-all to prevent raw exceptions from leaking to API clients.
        logger.exception("Unexpected upload error: %s", unexpected_error)
        if stored_file_path is not None:
            _remove_partial_file(stored_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during file upload.",
        ) from unexpected_error
    finally:
        # Ensure upload stream is always closed, even if validation fails.
        try:
            await file.close()
        except Exception as close_error:
            logger.warning("Failed to close upload stream: %s", close_error)
