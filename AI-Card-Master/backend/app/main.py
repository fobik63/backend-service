"""Main entrypoint for the AI-Card-Master FastAPI backend.

This module contains:
- app bootstrap and lifespan logic,
- CORS for Next.js frontends,
- OpenAPI / Swagger at /docs,
- global exception handlers,
- basic service endpoints.

Image upload lives in app.api.images (same path: POST /api/v1/images/upload).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api import (
    ab_tests_router,
    account_router,
    admin_router,
    admin_security_ws_router,
    ai_strategy_router,
    analytics_router,
    brand_dna_router,
    brand_loras_router,
    bulk_generations_router,
    captcha_router,
    claude_analyses_router,
    claude_reasoning_router,
    visual_audit_router,
    exports_router,
    generations_router,
    images_router,
    legal_router,
    marketplace_bridge_router,
    midjourney_webhook_router,
    oracle_router,
    pain_analysis_router,
    payments_router,
    referrals_router,
    smart_variants_router,
    text_generation_router,
    winback_router,
    workspaces_router,
)
from app.api.images import ensure_uploads_dir
from app.core.admin_middleware import AdminOnlyMiddleware
from app.core.cloudflare_middleware import CloudflareProtectionMiddleware
from app.core.config import get_settings
from app.core.dead_mans_switch_middleware import DeadMansSwitchMiddleware
from app.core.http_errors import shape_http_exception_body
from app.core.input_sanitization_middleware import InputSanitizationMiddleware
from app.core.logging_config import configure_logging
from app.core.request_context_middleware import RequestContextMiddleware
from app.core.suspicious_activity_middleware import SuspiciousActivityMiddleware
from app.infrastructure.redis import close_redis_client, close_security_redis_client, redis_healthcheck
from app.models.database import SessionLocal, engine
from app.services.ai_engine import close_ai_engine
from app.services.infographic_service import close_infographic_service
from app.services.marketplace_text import close_marketplace_text_service
from app.services.s3_storage import (
    S3StorageError,
    close_s3_storage,
    get_s3_storage,
)
from app.services.telegram_alerts import notify_critical_500


configure_logging()
logger = logging.getLogger(__name__)


class RootResponse(BaseModel):
    """Response schema for the root endpoint."""

    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    message: str = Field(..., description="Human-friendly welcome message")
    docs_url: str = Field(default="/docs", description="Swagger UI path")


class HealthResponse(BaseModel):
    """Response schema for health checks."""

    status: str = Field(..., description="Health status")
    detail: str = Field(..., description="Additional diagnostic detail")


class ReadinessResponse(BaseModel):
    """Dependency readiness without exposing credentials or internal URLs."""

    status: str
    dependencies: dict[str, bool]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and validate runtime resources.

    For now we only ensure the upload directory exists and is writable.
    """

    try:
        uploads_dir = ensure_uploads_dir()
        logger.info("Upload directory is ready: %s", uploads_dir)
    except OSError as startup_error:
        logger.exception("Startup failed: upload directory is not available")
        raise RuntimeError("Upload storage initialization failed") from startup_error

    try:
        yield
    finally:
        await close_ai_engine()
        await close_marketplace_text_service()
        await close_infographic_service()
        await close_security_redis_client()
        await close_redis_client()
        await close_s3_storage()
        await engine.dispose()


settings = get_settings()
_docs_enabled = settings.app_env != "production"

app = FastAPI(
    title="AI-Card-Master API",
    version="0.1.0",
    description=(
        "Backend API for AI-powered marketplace card generation. "
        "Interactive OpenAPI docs are available at `/docs` (Swagger UI) "
        "and `/redoc`."
    ),
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)


# CORS: allow Next.js (and other configured) frontends to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Security stack (Starlette: last added = outermost).
# Order: DeadMans → Cloudflare → RequestContext → Great Wall → Sanitization → AdminOnly → CORS → route.
app.add_middleware(AdminOnlyMiddleware)
app.add_middleware(InputSanitizationMiddleware)
app.add_middleware(SuspiciousActivityMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CloudflareProtectionMiddleware)
app.add_middleware(DeadMansSwitchMiddleware)


# Register API routers.
app.include_router(admin_router)
app.include_router(admin_security_ws_router)
app.include_router(analytics_router)
app.include_router(images_router)
app.include_router(legal_router)
app.include_router(account_router)
app.include_router(captcha_router)
app.include_router(payments_router)
app.include_router(referrals_router)
app.include_router(winback_router)
app.include_router(workspaces_router)
app.include_router(exports_router)
app.include_router(marketplace_bridge_router)
app.include_router(bulk_generations_router)
app.include_router(smart_variants_router)
app.include_router(brand_loras_router)
app.include_router(brand_dna_router)
app.include_router(claude_analyses_router)
app.include_router(claude_reasoning_router)
app.include_router(visual_audit_router)
app.include_router(oracle_router)
app.include_router(ai_strategy_router)
app.include_router(pain_analysis_router)
app.include_router(ab_tests_router)
app.include_router(generations_router)
app.include_router(text_generation_router)
app.include_router(midjourney_webhook_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Return consistent JSON for business and validation HTTP errors."""

    return JSONResponse(
        status_code=exc.status_code,
        content=shape_http_exception_body(exc),
        headers=exc.headers,
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
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unexpected exceptions and prevent trace leaks to clients."""

    logger.exception("Unhandled server error: %s", exc)
    await notify_critical_500(request, exc)
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
            docs_url="/docs",
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


@app.get("/health/live", response_model=HealthResponse, tags=["system"])
async def liveness() -> HealthResponse:
    """Process-only liveness; orchestration should restart on failure."""

    return HealthResponse(status="ok", detail="API process is alive.")


@app.get("/health/ready", response_model=ReadinessResponse, tags=["system"])
async def readiness(response: Response) -> ReadinessResponse:
    """Check critical dependencies while keeping liveness independent."""

    database_ready = False
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_ready = True
    except Exception:
        logger.warning("Database readiness check failed", exc_info=True)

    redis_ready = await redis_healthcheck()
    s3_ready = False
    try:
        s3_ready = await get_s3_storage().healthcheck()
    except S3StorageError:
        logger.warning("S3 readiness check failed", exc_info=True)

    dependencies = {
        "postgresql": database_ready,
        "redis": redis_ready,
        "s3": s3_ready,
    }
    critical_ready = database_ready and s3_ready
    fully_ready = critical_ready and redis_ready
    if not critical_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if fully_ready else "degraded",
        dependencies=dependencies,
    )
