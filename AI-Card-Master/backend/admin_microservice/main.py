"""Isolated admin-panel microservice.

Runs as a separate process (default 127.0.0.1:8100) and is reachable only with
an AES-256-GCM encrypted admin token (``Authorization: Bearer adm.v1....`` or
``X-Admin-Token``). Reuses ``AdminService`` from the main backend package —
existing monolith ``/api/v1/admin`` JWT routes are left intact.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import AsyncGenerator, Literal
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_log_schemas import (
    AuditArchiveResponse,
    AuditSearchResponse,
    archive_result_to_response,
    search_result_to_response,
)
from app.api.cost_analytics_schemas import (
    CostDashboardResponse,
)
from app.api.cost_analytics_schemas import (
    snapshot_to_response as cost_snapshot_to_response,
)
from app.api.security_status_schemas import (
    BlockedThreatEventResponse,
    BlockedThreatsLogResponse,
    SecurityStatusResponse,
    snapshot_to_dict,
    snapshot_to_response,
)
from app.application.audit_log_service import AuditLogService
from app.application.cost_analytics_service import CostAnalyticsService
from app.application.security_status_service import SecurityStatusService
from app.core.admin_token import AdminTokenClaims, AdminTokenError, verify_admin_panel_token
from app.core.cloudflare_middleware import CloudflareProtectionMiddleware
from app.core.config import get_settings
from app.core.dead_mans_switch_middleware import DeadMansSwitchMiddleware
from app.core.request_context_middleware import RequestContextMiddleware
from app.core.suspicious_activity_middleware import SuspiciousActivityMiddleware
from app.domain.audit_log import AuditEventType, AuditSearchQuery
from app.infrastructure.audit_log_factory import build_audit_log_service
from app.infrastructure.cost_analytics_factory import build_cost_analytics_service
from app.infrastructure.security_status_factory import get_security_status_service
from app.models.database import engine, get_db_session
from app.models.enums import SubscriptionStatus
from app.services.admin_service import (
    AdminApiCostStatistics,
    AdminCounterStats,
    AdminNotFoundError,
    AdminPaymentStatistics,
    AdminService,
    AdminStatistics,
    AdminUserView,
    AdminValidationError,
)
from app.services.dead_mans_switch import (
    AuthFailureEvent,
    DeadMansSwitchState,
    extract_source_ip,
    get_dead_mans_switch,
    looks_like_db_auth_failure,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("admin_microservice")


class StrictAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class AdminStatisticsResponse(StrictAdminModel):
    generations_today: int
    generations_last_7_days: int
    total_generations: int
    total_users: int
    registrations_today: int
    registrations_last_7_days: int
    total_payments: int
    successful_payments: int
    total_revenue_rub: Decimal
    active_pro_subscriptions: int
    api_cost_total_usd: Decimal
    midjourney_cost_total_usd: Decimal
    claude_47_cost_total_usd: Decimal


class AdminCounterStatsResponse(StrictAdminModel):
    total: int
    today: int
    last_7_days: int


class AdminPaymentStatsResponse(StrictAdminModel):
    total: int
    successful: int
    today: int
    last_7_days: int
    total_revenue_rub: Decimal


class AdminApiCostStatsResponse(StrictAdminModel):
    events_total: int
    total_cost_usd: Decimal
    midjourney_cost_usd: Decimal
    claude_47_cost_usd: Decimal


class AdminUserResponse(StrictAdminModel):
    id: str
    email: str
    is_admin: bool
    subscription_status: SubscriptionStatus
    ai_coins: int
    is_banned: bool
    ban_reason: str | None = None
    banned_at: datetime | None = None
    created_at: datetime


class AdminUserActionRequest(StrictAdminModel):
    action: Literal["grant_credits", "ban", "unban"]
    user_id: str | None = Field(default=None)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    credits: int | None = Field(default=None, gt=0, le=1_000_000)
    reason: str | None = Field(default=None, min_length=2, max_length=2000)


class AdminUpdateSubscriptionRequest(StrictAdminModel):
    email: str = Field(..., min_length=3, max_length=320)
    subscription_status: SubscriptionStatus

    @field_validator("subscription_status", mode="before")
    @classmethod
    def parse_subscription_status(cls, value: object) -> SubscriptionStatus:
        if isinstance(value, SubscriptionStatus):
            return value
        if isinstance(value, str):
            return SubscriptionStatus(value)
        raise ValueError("subscription_status must be a valid subscription value.")


class DeadMansSwitchStatusResponse(StrictAdminModel):
    active: bool
    triggered_at: str | None = None
    reason: str | None = None
    source_ip: str | None = None
    fail_count: int = 0
    cloudflare_under_attack: bool = False
    host_lockdown: bool = False


class DbAuthFailureReportRequest(StrictAdminModel):
    """Ingest a Postgres auth-failure observation from the host watchdog."""

    line: str = Field(..., min_length=8, max_length=4000)
    source_ip: str | None = Field(default=None, max_length=64)
    user: str | None = Field(default=None, max_length=128)


class DeadMansTriggerRequest(StrictAdminModel):
    reason: str = Field(..., min_length=4, max_length=1000)
    source_ip: str = Field(default="manual", max_length=64)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    secret = settings.admin_panel_token_secret.get_secret_value().strip()
    if not secret and settings.app_env == "production":
        raise RuntimeError(
            "ADMIN_PANEL_TOKEN_SECRET is required for the admin microservice in production."
        )
    logger.info(
        "Admin microservice starting on %s:%s",
        settings.admin_panel_bind_host,
        settings.admin_panel_port,
    )
    try:
        yield
    finally:
        await engine.dispose()


settings = get_settings()

app = FastAPI(
    title="AI-Card-Master Admin Panel API",
    version="0.1.0",
    description="Isolated admin statistics/management API. Token auth only.",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)

if settings.admin_panel_cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.admin_panel_cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "X-Admin-Token", "Content-Type"],
    )

app.add_middleware(CloudflareProtectionMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SuspiciousActivityMiddleware)
app.add_middleware(DeadMansSwitchMiddleware)


def _extract_raw_token(
    authorization: str | None,
    x_admin_token: str | None,
) -> str:
    if x_admin_token and x_admin_token.strip():
        return x_admin_token.strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
        if authorization.strip().startswith("adm.v1."):
            return authorization.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Encrypted admin panel token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin_panel_token(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminTokenClaims:
    """Verify the encrypted admin-panel service token."""

    raw = _extract_raw_token(authorization, x_admin_token)
    try:
        return verify_admin_panel_token(
            raw,
            secret=get_settings().effective_admin_panel_token_secret,
        )
    except AdminTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin panel token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_admin_service(db_session: AsyncSession = Depends(get_db_session)) -> AdminService:
    return AdminService(db_session)


def _admin_user_response(user: AdminUserView) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        subscription_status=SubscriptionStatus(user.subscription_status),
        ai_coins=user.ai_coins,
        is_banned=user.is_banned,
        ban_reason=user.ban_reason,
        banned_at=user.banned_at,
        created_at=user.created_at,
    )


def _parse_optional_user_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id must be a valid UUID.",
        ) from exc


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "admin-panel"}


def _dms_response(state: DeadMansSwitchState) -> DeadMansSwitchStatusResponse:
    return DeadMansSwitchStatusResponse(
        active=state.active,
        triggered_at=state.triggered_at,
        reason=state.reason,
        source_ip=state.source_ip,
        fail_count=state.fail_count,
        cloudflare_under_attack=state.cloudflare_under_attack,
        host_lockdown=state.host_lockdown,
    )


@app.get(
    "/security/dead-mans-switch",
    response_model=DeadMansSwitchStatusResponse,
    tags=["security"],
)
@app.get(
    "/security/dead-mans-switch/status",
    response_model=DeadMansSwitchStatusResponse,
    tags=["security"],
)
async def dead_mans_switch_status(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
) -> DeadMansSwitchStatusResponse:
    """Return current Dead Man's Switch lockdown state."""

    return _dms_response(await get_dead_mans_switch().get_state())


@app.post(
    "/security/dead-mans-switch/db-auth-failure",
    response_model=DeadMansSwitchStatusResponse,
    tags=["security"],
)
async def report_db_auth_failure(
    payload: DbAuthFailureReportRequest,
    _: AdminTokenClaims = Depends(require_admin_panel_token),
) -> DeadMansSwitchStatusResponse:
    """Admin panel ingestion point for Postgres password brute-force events.

    The host watchdog (`deploy/dead_mans_watchdog.py`) tails Postgres logs and
    POSTs matching lines here. Crossing ``DEAD_MANS_SWITCH_FAIL_THRESHOLD``
    within the sliding window activates full external lockdown + Telegram.
    """

    if not looks_like_db_auth_failure(payload.line):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Line does not look like a PostgreSQL authentication failure.",
        )
    source_ip = (payload.source_ip or "").strip() or extract_source_ip(payload.line)
    event = AuthFailureEvent(
        source_ip=source_ip,
        raw_line=payload.line[:500],
        user=payload.user,
    )
    state = await get_dead_mans_switch().record_auth_failure(event)
    return _dms_response(state)


@app.post(
    "/security/dead-mans-switch/trigger",
    response_model=DeadMansSwitchStatusResponse,
    tags=["security"],
)
async def trigger_dead_mans_switch(
    payload: DeadMansTriggerRequest,
    _: AdminTokenClaims = Depends(require_admin_panel_token),
) -> DeadMansSwitchStatusResponse:
    """Manually arm Dead Man's Switch (drill / confirmed incident)."""

    state = await get_dead_mans_switch().trigger(
        reason=payload.reason,
        source_ip=payload.source_ip,
        fail_count=0,
    )
    return _dms_response(state)


@app.post(
    "/security/dead-mans-switch/clear",
    response_model=DeadMansSwitchStatusResponse,
    tags=["security"],
)
async def clear_dead_mans_switch(
    claims: AdminTokenClaims = Depends(require_admin_panel_token),
) -> DeadMansSwitchStatusResponse:
    """Clear lockdown after investigation (VPN / localhost only recommended)."""

    operator = claims.operator_label or "admin"
    state = await get_dead_mans_switch().clear(operator=str(operator))
    return _dms_response(state)


def _security_status_service() -> SecurityStatusService:
    return get_security_status_service()


@app.get(
    "/security/status",
    response_model=SecurityStatusResponse,
    tags=["security"],
)
async def get_security_status(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    threats_limit: int = Query(default=50, ge=1, le=50),
    service: SecurityStatusService = Depends(_security_status_service),
) -> SecurityStatusResponse:
    """Live CPU/RAM/RPS + Midjourney/Claude balance + blocked threats."""

    snapshot = await service.get_snapshot(threats_limit=threats_limit)
    return snapshot_to_response(snapshot)


@app.get(
    "/security/threats",
    response_model=BlockedThreatsLogResponse,
    tags=["security"],
)
async def get_blocked_threats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    limit: int = Query(default=50, ge=1, le=50),
    service: SecurityStatusService = Depends(_security_status_service),
) -> BlockedThreatsLogResponse:
    """JSON log of the last blocked threats (max 50)."""

    snapshot = await service.get_snapshot(threats_limit=limit)
    threats = [
        BlockedThreatEventResponse(
            id=item.id,
            timestamp=item.timestamp,
            ip=item.ip,
            category=item.category,
            path=item.path,
            action=item.action,
            http_status=item.http_status,
            score=item.score,
            api_key_fingerprint=item.api_key_fingerprint,
        )
        for item in snapshot.blocked_threats
    ]
    return BlockedThreatsLogResponse(threats=threats, count=len(threats))


@app.websocket("/security/status/ws")
async def security_status_websocket(websocket: WebSocket) -> None:
    """Real-time Security & Status stream (admin panel token required)."""

    await websocket.accept()
    raw = (
        (websocket.query_params.get("admin_token") or "").strip()
        or (websocket.query_params.get("token") or "").strip()
    )
    if not raw:
        auth_header = websocket.headers.get("authorization") or ""
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            raw = value.strip()
        elif auth_header.strip().startswith("adm.v1."):
            raw = auth_header.strip()
    if not raw:
        await websocket.close(code=4401)
        return
    try:
        verify_admin_panel_token(
            raw,
            secret=get_settings().effective_admin_panel_token_secret,
        )
    except AdminTokenError:
        await websocket.close(code=4401)
        return

    service = get_security_status_service()
    interval = get_settings().security_status_ws_interval_seconds
    try:
        while True:
            snapshot = await service.get_snapshot(threats_limit=50)
            await websocket.send_json(snapshot_to_dict(snapshot))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.debug("Admin microservice security status WS disconnected")
    except Exception:
        logger.exception("Admin microservice security status WS failed")
        try:
            await websocket.close(code=1011)
        except Exception:
            return


@app.get("/stats", response_model=AdminStatisticsResponse)
async def get_admin_stats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminStatisticsResponse:
    try:
        stats: AdminStatistics = await admin_service.get_statistics()
        return AdminStatisticsResponse(
            generations_today=stats.generations_today,
            generations_last_7_days=stats.generations_last_7_days,
            total_generations=stats.total_generations,
            total_users=stats.total_users,
            registrations_today=stats.registrations_today,
            registrations_last_7_days=stats.registrations_last_7_days,
            total_payments=stats.total_payments,
            successful_payments=stats.successful_payments,
            total_revenue_rub=stats.total_revenue_rub,
            active_pro_subscriptions=stats.active_pro_subscriptions,
            api_cost_total_usd=stats.api_cost_total_usd,
            midjourney_cost_total_usd=stats.midjourney_cost_total_usd,
            claude_47_cost_total_usd=stats.claude_47_cost_total_usd,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch admin statistics.",
        ) from exc


@app.get("/stats/registrations", response_model=AdminCounterStatsResponse)
async def get_registration_stats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminCounterStatsResponse:
    stats: AdminCounterStats = await admin_service.get_registration_statistics()
    return AdminCounterStatsResponse(**asdict(stats))


@app.get("/stats/payments", response_model=AdminPaymentStatsResponse)
async def get_payment_stats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminPaymentStatsResponse:
    stats: AdminPaymentStatistics = await admin_service.get_payment_statistics()
    return AdminPaymentStatsResponse(**asdict(stats))


@app.get("/stats/generations", response_model=AdminCounterStatsResponse)
async def get_generation_stats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminCounterStatsResponse:
    stats: AdminCounterStats = await admin_service.get_generation_statistics()
    return AdminCounterStatsResponse(**asdict(stats))


@app.get("/monitoring/api-costs", response_model=AdminApiCostStatsResponse)
async def get_api_cost_stats(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminApiCostStatsResponse:
    stats: AdminApiCostStatistics = await admin_service.get_api_cost_statistics()
    return AdminApiCostStatsResponse(**asdict(stats))


async def _cost_analytics_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> CostAnalyticsService:
    return build_cost_analytics_service(db_session)


@app.get("/costs", response_model=CostDashboardResponse, tags=["costs"])
async def get_ai_cost_dashboard(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    expensive_limit: int = Query(default=10, ge=1, le=50),
    notify_alerts: bool = Query(default=False),
    service: CostAnalyticsService = Depends(_cost_analytics_service),
) -> CostDashboardResponse:
    """AI Cost Dashboard: today/week/month, providers, top ops, profitability, alerts."""

    snapshot = await service.get_dashboard(
        expensive_limit=expensive_limit,
        notify_alerts=notify_alerts,
    )
    return cost_snapshot_to_response(snapshot)


async def _audit_log_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> AuditLogService:
    return build_audit_log_service(db_session, fail_open=False)


@app.get("/audit-logs", response_model=AuditSearchResponse, tags=["audit"])
async def search_audit_logs(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    user_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    ip: str | None = Query(default=None, max_length=64),
    request_id: str | None = Query(default=None, max_length=64),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: AuditLogService = Depends(_audit_log_service),
) -> AuditSearchResponse:
    """Search enterprise audit events by user / type / date / IP / request_id."""

    parsed_type: AuditEventType | None = None
    if event_type is not None and event_type.strip():
        try:
            parsed_type = AuditEventType(event_type.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown event_type: {event_type}",
            ) from exc

    result = await service.search_events(
        AuditSearchQuery(
            user_id=user_id,
            event_type=parsed_type,
            ip=ip,
            request_id=request_id,
            created_from=created_from,
            created_to=created_to,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )
    return search_result_to_response(result)


@app.post("/audit-logs/archive", response_model=AuditArchiveResponse, tags=["audit"])
async def archive_audit_logs(
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    service: AuditLogService = Depends(_audit_log_service),
) -> AuditArchiveResponse:
    result = await service.archive_old_events()
    return archive_result_to_response(result)


@app.get("/users/by-email", response_model=AdminUserResponse)
async def get_user_by_email(
    email: str = Query(..., min_length=3, max_length=320),
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    try:
        user = await admin_service.find_user_by_email(email)
        return _admin_user_response(user)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.patch("/users/subscription", response_model=AdminUserResponse)
async def update_user_subscription(
    payload: AdminUpdateSubscriptionRequest,
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    try:
        user = await admin_service.update_user_subscription_status(
            email=payload.email,
            subscription_status=payload.subscription_status,
        )
        return _admin_user_response(user)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/users/actions", response_model=AdminUserResponse)
async def manage_user_action(
    payload: AdminUserActionRequest,
    _: AdminTokenClaims = Depends(require_admin_panel_token),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    parsed_user_id = _parse_optional_user_id(payload.user_id)
    try:
        if payload.action == "grant_credits":
            if payload.credits is None:
                raise AdminValidationError("credits is required for grant_credits.")
            user = await admin_service.grant_user_credits(
                user_id=parsed_user_id,
                email=payload.email,
                amount=payload.credits,
            )
        elif payload.action == "ban":
            if payload.reason is None:
                raise AdminValidationError("reason is required for ban.")
            user = await admin_service.ban_user(
                user_id=parsed_user_id,
                email=payload.email,
                reason=payload.reason,
            )
        else:
            user = await admin_service.unban_user(
                user_id=parsed_user_id,
                email=payload.email,
            )
        return _admin_user_response(user)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Admin microservice error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "detail": "Internal server error."},
    )
