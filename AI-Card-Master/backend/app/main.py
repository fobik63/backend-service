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

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api import (
    ab_tests_router,
    account_router,
    admin_router,
    admin_security_ws_router,
    ai_strategy_router,
    analytics_router,
    auth_router,
    brand_dna_router,
    brand_loras_router,
    bulk_generations_router,
    captcha_router,
    claude_analyses_router,
    claude_reasoning_router,
    designs_router,
    visual_audit_router,
    exports_router,
    generations_router,
    health_router,
    images_router,
    fonts_router,
    legal_router,
    marketplace_bridge_router,
    midjourney_webhook_router,
    oracle_router,
    pain_analysis_router,
    payments_router,
    referrals_router,
    smart_variants_router,
    templates_router,
    text_generation_router,
    winback_router,
    workspaces_router,
)
from app.api.images import ensure_uploads_dir
from app.core.admin_middleware import AdminOnlyMiddleware
from app.core.cloudflare_middleware import CloudflareProtectionMiddleware
from app.core.config import get_settings
from app.core.dead_mans_switch_middleware import DeadMansSwitchMiddleware
from app.core.http_errors import shape_error_envelope, shape_http_exception_body
from app.core.idempotency_middleware import IdempotencyMiddleware
from app.core.input_sanitization_middleware import InputSanitizationMiddleware
from app.core.logging_config import configure_logging
from app.core.payload_size_limiter_middleware import PayloadSizeLimiterMiddleware
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.request_context_middleware import RequestContextMiddleware
from app.core.security_headers_middleware import SecurityHeadersMiddleware
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
from app.infrastructure.observability.sentry import (
    capture_unhandled_exception,
    init_sentry,
)
from app.services.telegram_alerts import notify_critical_500, resolve_request_user_id
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

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


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_OPENAPI_EXPORT_PATH = _BACKEND_ROOT / "docs" / "openapi.json"
_ALEMBIC_INI_PATH = _BACKEND_ROOT / "alembic.ini"


def export_openapi_schema(application: FastAPI, destination: Path) -> Path:
    """Write the live OpenAPI document to disk for frontend / SDK sync."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    schema = application.openapi()
    destination.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _is_database_connection_error(exc: BaseException) -> bool:
    """Return True when the failure is a DB connectivity / DNS / timeout issue."""

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    if isinstance(exc, (OperationalError, InterfaceError, DBAPIError)):
        return True

    message = str(exc).lower()
    markers = (
        "could not connect",
        "connection refused",
        "connection reset",
        "connect call failed",
        "name or service not known",
        "temporary failure in name resolution",
        "timeout expired",
        "server closed the connection",
        "network is unreachable",
        "actively refused",
        "cannot connect to server",
        "connection is closed",
        "no route to host",
    )
    return any(marker in message for marker in markers)


def _load_alembic_upgrade_api() -> tuple[object, type]:
    """Import ``alembic.command`` / ``Config`` from the installed distribution.

    The backend keeps migrations under a local package named ``alembic/``, which
    shadows the PyPI package on ``sys.path``. Temporarily prefer site-packages
    so ``command.upgrade`` resolves correctly.
    """

    import importlib
    import sys

    backend_root = _BACKEND_ROOT.resolve()
    local_migrations = (backend_root / "alembic").resolve()

    def _is_local_migrations_module(module: object) -> bool:
        paths = getattr(module, "__path__", None)
        if paths:
            for entry in paths:
                try:
                    if Path(entry).resolve() == local_migrations:
                        return True
                except OSError:
                    continue
        file_name = getattr(module, "__file__", None)
        if not file_name:
            return False
        try:
            return local_migrations in Path(file_name).resolve().parents or (
                Path(file_name).resolve().parent == local_migrations
            )
        except OSError:
            return False

    for module_name in list(sys.modules):
        if module_name == "alembic" or module_name.startswith("alembic."):
            module = sys.modules.get(module_name)
            if module is None or _is_local_migrations_module(module):
                del sys.modules[module_name]

    original_sys_path = list(sys.path)
    filtered_path: list[str] = []
    for entry in original_sys_path:
        if entry in ("", "."):
            continue
        try:
            if Path(entry).resolve() == backend_root:
                continue
        except OSError:
            pass
        filtered_path.append(entry)

    sys.path[:] = filtered_path
    try:
        command_module = importlib.import_module("alembic.command")
        config_module = importlib.import_module("alembic.config")
    finally:
        sys.path[:] = original_sys_path

    return command_module, config_module.Config


def apply_alembic_migrations() -> None:
    """Apply pending Alembic migrations to ``head``.

    Connection errors are logged and swallowed so the API can still boot in
    local/dev environments where Postgres is intentionally offline. Schema
    migration failures with a reachable database are re-raised.
    """

    if not _ALEMBIC_INI_PATH.is_file():
        logger.error("Alembic config not found at %s", _ALEMBIC_INI_PATH)
        raise FileNotFoundError(f"Missing Alembic config: {_ALEMBIC_INI_PATH}")

    command, config_cls = _load_alembic_upgrade_api()
    alembic_cfg = config_cls(str(_ALEMBIC_INI_PATH))
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        if _is_database_connection_error(exc):
            logger.warning(
                "Auto-migrate skipped: database is unreachable (%s)",
                exc,
            )
            return
        logger.exception("Auto-migrate failed while applying Alembic upgrades")
        raise
    logger.info("Alembic migrations applied successfully (head)")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and validate runtime resources.

    Ensures the upload directory exists and auto-applies Alembic migrations.
    """

    try:
        uploads_dir = ensure_uploads_dir()
        logger.info("Upload directory is ready: %s", uploads_dir)
    except OSError as startup_error:
        logger.exception("Startup failed: upload directory is not available")
        raise RuntimeError("Upload storage initialization failed") from startup_error

    # Run in a worker thread: alembic/env.py uses asyncio.run() for async engines.
    await asyncio.to_thread(apply_alembic_migrations)

    # Register default Cyrillic fonts from assets/fonts into FontRegistry (+ DB).
    try:
        from app.services.templates.font_manager import get_font_manager_service

        font_manager = get_font_manager_service()
        registered = await font_manager.bootstrap(persist_system_fonts=True)
        logger.info("FontManager registered %s system font file(s)", registered)
    except Exception:
        logger.exception(
            "FontManager bootstrap failed; canvas rendering will use "
            "FontRegistry discovery / Pillow defaults"
        )

    runtime_settings = get_settings()
    if runtime_settings.app_env == "development":
        try:
            path = export_openapi_schema(application, _OPENAPI_EXPORT_PATH)
            logger.info("OpenAPI schema exported to %s", path)
        except OSError:
            logger.exception("Failed to export OpenAPI schema on startup")

    try:
        yield
    finally:
        await close_ai_engine()
        await close_marketplace_text_service()
        await close_infographic_service()
        try:
            from app.services.three_d.factory import close_three_d_engine

            await close_three_d_engine()
        except Exception:
            logger.exception("Failed to close 3D engine on shutdown")
        await close_security_redis_client()
        await close_redis_client()
        await close_s3_storage()
        try:
            from app.services.templates.image_cache import get_image_asset_cache

            await get_image_asset_cache().aclose()
        except Exception:
            logger.exception("Failed to close canvas image asset cache on shutdown")
        await engine.dispose()


settings = get_settings()
init_sentry(settings)
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


# Cascading slowapi rate limits (Redis). Must be attached before middleware.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


def _is_routing_not_found(exc: StarletteHTTPException) -> bool:
    """True for Starlette/FastAPI unmatched-route 404s (not business NotFound)."""

    detail = exc.detail
    if detail in {"Not Found", "not found"}:
        return True
    return isinstance(detail, str) and detail.strip().lower() == "not found"


# CORS: allow only explicitly configured frontend origins (ALLOWED_ORIGINS).
# Wildcard origins/methods/headers are rejected in production via Settings.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods_list,
    allow_headers=settings.cors_allow_headers_list,
    expose_headers=settings.cors_expose_headers_list,
    max_age=600,
)
# Security stack (Starlette: last added = outermost).
# Order: SlowAPI → DeadMans → SecurityHeaders → Cloudflare → PayloadSize
#        → RequestContext → Great Wall → Sanitization → Idempotency
#        → AdminOnly → CORS → route.
app.add_middleware(AdminOnlyMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(InputSanitizationMiddleware)
app.add_middleware(SuspiciousActivityMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(PayloadSizeLimiterMiddleware)
app.add_middleware(CloudflareProtectionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(DeadMansSwitchMiddleware)
app.add_middleware(SlowAPIASGIMiddleware)


# Register API routers.
# Isolated infra probes (/healthz, /readyz) — outside /api/v1.
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(admin_security_ws_router)
app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(images_router)
app.include_router(fonts_router)
app.include_router(templates_router)
app.include_router(designs_router)
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

# 3D Generation — feature-toggled (ENABLE_THREE_D) so disabled envs stay lean.
if settings.enable_three_d:
    from app.api.three_d import router as three_d_router
    from app.api.three_d_video import router as three_d_video_router
    from app.api.three_d_ws import router as three_d_ws_router

    app.include_router(three_d_router)
    app.include_router(three_d_video_router)
    app.include_router(three_d_ws_router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Return consistent JSON for business and validation HTTP errors.

    Unmatched routes raise Starlette ``HTTPException(404, detail='Not Found')``;
    those are shaped as the stable Resource Not Found envelope (with path).
    Intentional business 404s keep ``success`` / ``detail``.
    """

    if exc.status_code == status.HTTP_404_NOT_FOUND and _is_routing_not_found(exc):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "Resource Not Found",
                "code": 404,
                "path": request.url.path,
            },
            headers=exc.headers,
        )

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
            **shape_error_envelope(
                code="request_validation_error",
                message="Request validation failed.",
            ),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unexpected exceptions and prevent trace leaks to clients.

    Forwards the event to Sentry (PII-scrubbed) and sends a short Telegram
    admin alert with file/line/endpoint/user_id via httpx.
    """

    logger.exception("Unhandled server error: %s", exc)
    capture_unhandled_exception(exc, user_id=resolve_request_user_id(request))
    await notify_critical_500(request, exc)
    # Never leak stack traces / exception strings to clients.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "detail": "Internal server error.",
            **shape_error_envelope(
                code="internal_server_error",
                message="Internal server error.",
            ),
        },
    )


@app.get("/", response_model=RootResponse, tags=["system"])
@limiter.exempt
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
@limiter.exempt
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
@limiter.exempt
async def liveness() -> HealthResponse:
    """Process-only liveness; orchestration should restart on failure.

    Prefer ``GET /healthz`` for Kubernetes-style probes (minimal JSON body).
    """

    return HealthResponse(status="ok", detail="API process is alive.")


@app.get("/health/ready", response_model=ReadinessResponse, tags=["system"])
@limiter.exempt
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
