"""Analytics API: style-preset insights + manual competitor-link audit."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.competitor_audit_service import (
    CompetitorAuditNotFoundError,
    CompetitorAuditService,
    CompetitorAuditValidationError,
)
from app.application.style_analytics_service import (
    StyleAnalyticsService,
    StyleAnalyticsValidationError,
    load_niche_titles_from_catalog,
)
from app.config.style_presets import load_style_presets
from app.domain.competitor_audit import (
    MAX_LINKS_PER_REQUEST,
    CompetitorAuditEnqueueRequest,
    CompetitorAuditJobStatus,
)
from app.domain.style_analytics import InsightMetric, InsightPriority
from app.infrastructure.celery_app import celery_app
from app.infrastructure.competitor_audit_factory import build_competitor_audit_service
from app.infrastructure.persistence.style_analytics_repository import StyleAnalyticsRepository
from app.models.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class StrictAPIModel(BaseModel):
    """Strict API contract (forbid unknown fields)."""

    model_config = ConfigDict(extra="forbid", strict=True)


class StyleAiInsightResponse(StrictAPIModel):
    """AI insight attached to a popular style preset."""

    code: str
    message: str = Field(
        ...,
        description='Human-readable insight, e.g. "Этот фон повышает CTR на 15%"',
    )
    metric: InsightMetric
    estimated_lift_percent: float
    confidence: float
    rationale: str


class TopStylePresetResponse(StrictAPIModel):
    """One ranked style preset with selection stats and AI insight."""

    rank: int
    niche_key: str
    niche_title: str
    slide_key: str
    selected_style: str
    selection_count: int
    share_percent: float
    ai_insight: StyleAiInsightResponse


class NicheBreakdownResponse(StrictAPIModel):
    """Niche-level popularity slice."""

    niche_key: str
    niche_title: str
    selection_count: int
    share_percent: float
    top_style: str | None = None


class StyleAiRecommendationResponse(StrictAPIModel):
    """Actionable AI recommendation for the product UI."""

    code: str
    priority: InsightPriority
    message: str
    niche_key: str
    selected_style: str
    slide_key: str
    metric: InsightMetric
    estimated_lift_percent: float


class StylePresetAnalyticsResponse(StrictAPIModel):
    """JSON analytics payload for internal style-preset tracking.

    Example shape::

        {
          "generated_at": "2026-08-06T18:00:00Z",
          "period_days": 30,
          "total_selections": 1500,
          "unique_presets": 15,
          "top_presets": [
            {
              "rank": 1,
              "niche_key": "perfume",
              "niche_title": "Парфюмерия",
              "slide_key": "cover",
              "selected_style": "studio hero bottle",
              "selection_count": 320,
              "share_percent": 21.3,
              "ai_insight": {
                "code": "ctr_lift_cover",
                "message": "Этот фон повышает CTR на 15%",
                "metric": "ctr",
                "estimated_lift_percent": 15.0,
                "confidence": 0.84,
                "rationale": "..."
              }
            }
          ],
          "by_niche": [...],
          "ai_recommendations": [...]
        }
    """

    generated_at: datetime
    period_days: int
    total_selections: int
    unique_presets: int
    top_presets: list[TopStylePresetResponse]
    by_niche: list[NicheBreakdownResponse]
    ai_recommendations: list[StyleAiRecommendationResponse]


class AnalyzeLinksRequest(StrictAPIModel):
    """Manual competitor audit: 1–3 WB/Ozon product URLs."""

    links: list[str] = Field(
        min_length=1,
        max_length=MAX_LINKS_PER_REQUEST,
        description="Wildberries / Ozon product links (max 3).",
    )


class AnalyzeLinksEnqueueResponse(StrictAPIModel):
    """HTTP 202 payload: durable task_id for polling."""

    task_id: UUID
    status: CompetitorAuditJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    links_count: int = Field(ge=1, le=MAX_LINKS_PER_REQUEST)


class AnalyzeLinksJobResponse(StrictAPIModel):
    """Poll response for competitor deep-scrape + Claude deep-analysis job."""

    task_id: UUID
    status: CompetitorAuditJobStatus
    status_url: str
    links: list[str]
    celery_task_id: str | None = None
    result: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Claude deep analysis: competitor_weaknesses, conversion_triggers, "
            "actionable_blueprint per card; cross_check (OCR↔description, "
            "verdict «Аномалия» on contradictions) + advice_reliability_pct 0–100%; "
            "insufficient_data when evidence is too thin to invent weaknesses."
        ),
    )
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_message: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


async def get_style_analytics_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> StyleAnalyticsService:
    """Request-scoped style analytics use case."""

    try:
        catalog = load_style_presets()
    except Exception:
        catalog = None
    return StyleAnalyticsService(
        StyleAnalyticsRepository(db_session),
        niche_titles=load_niche_titles_from_catalog(catalog),
    )


def get_competitor_audit_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> CompetitorAuditService:
    """Request-scoped competitor-link audit use case (enqueue/poll only)."""

    return build_competitor_audit_service(
        db_session,
        enqueue_analysis=False,
        require_claude_client=False,
    )


def _analyze_links_job_response(job) -> AnalyzeLinksJobResponse:
    return AnalyzeLinksJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/analytics/analyze-links/{job.id}",
        links=list(job.links_payload),
        celery_task_id=job.celery_task_id,
        result=job.result_payload,
        analysis=job.analysis_payload,
        model_name=job.model_name,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.post(
    "/analyze-links",
    response_model=AnalyzeLinksEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue deep scrape of competitor WB/Ozon product links",
)
async def analyze_competitor_links(
    body: AnalyzeLinksRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: CompetitorAuditService = Depends(get_competitor_audit_service),
) -> AnalyzeLinksEnqueueResponse:
    """Accept ≤3 marketplace links and return task_id immediately (Celery scrape).

    Worker pulls gallery photos, description, specs, prices before/after discount,
    and the last 50 reviews split into 1–3★ vs 4–5★. Raw parse log is cached in
    Redis for 1 hour. Immediately after scrape, Claude 4.7 Opus Vision runs a
    three-vector deep analysis (visual / reviews / market gap) and stores
    competitor_weaknesses, conversion_triggers, actionable_blueprint for the UI.
    """

    try:
        request = CompetitorAuditEnqueueRequest(links=body.links)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        job, replay = await service.enqueue_audit(
            user_id=current_user.id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except CompetitorAuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    celery_task_id = job.celery_task_id
    if not replay or not celery_task_id:
        async_result = celery_app.send_task(
            "analytics.run_competitor_audit",
            args=[str(job.id)],
            queue="analytics.scrape",
        )
        celery_task_id = async_result.id
        job = await service.attach_celery_task(
            job_id=job.id,
            celery_task_id=celery_task_id,
        )

    return AnalyzeLinksEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/analytics/analyze-links/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        links_count=len(job.links_payload),
    )


@router.get(
    "/analyze-links/{task_id}",
    response_model=AnalyzeLinksJobResponse,
    summary="Poll competitor-link deep-scrape + Claude deep-analysis job",
)
async def get_analyze_links_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CompetitorAuditService = Depends(get_competitor_audit_service),
) -> AnalyzeLinksJobResponse:
    """Return scrape status, raw cards, and Claude deep-analysis JSON when ready."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except CompetitorAuditNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _analyze_links_job_response(job)


@router.get(
    "/style-presets",
    response_model=StylePresetAnalyticsResponse,
    summary="Style preset popularity and AI insights",
)
async def get_style_preset_analytics(
    period_days: int = Query(default=30, ge=1, le=365),
    niche_key: str | None = Query(
        default=None,
        max_length=64,
        description="Optional niche filter: perfume | clothing | electronics",
    ),
    top_limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    analytics: StyleAnalyticsService = Depends(get_style_analytics_service),
) -> StylePresetAnalyticsResponse:
    """Return which style presets are chosen most often plus AI lift insights.

    Selection events are written to PostgreSQL when a generation job is created.
    Insights are derived from internal frequency + slide role (e.g. cover → CTR).
    """

    _ = current_user
    try:
        payload = await analytics.get_preset_analytics(
            period_days=period_days,
            niche_key=niche_key,
            top_limit=top_limit,
        )
    except StyleAnalyticsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return StylePresetAnalyticsResponse(
        generated_at=payload.generated_at,
        period_days=payload.period_days,
        total_selections=payload.total_selections,
        unique_presets=payload.unique_presets,
        top_presets=[
            TopStylePresetResponse(
                rank=item.rank,
                niche_key=item.niche_key,
                niche_title=item.niche_title,
                slide_key=item.slide_key,
                selected_style=item.selected_style,
                selection_count=item.selection_count,
                share_percent=item.share_percent,
                ai_insight=StyleAiInsightResponse(
                    code=item.ai_insight.code,
                    message=item.ai_insight.message,
                    metric=item.ai_insight.metric,
                    estimated_lift_percent=item.ai_insight.estimated_lift_percent,
                    confidence=item.ai_insight.confidence,
                    rationale=item.ai_insight.rationale,
                ),
            )
            for item in payload.top_presets
        ],
        by_niche=[
            NicheBreakdownResponse(
                niche_key=item.niche_key,
                niche_title=item.niche_title,
                selection_count=item.selection_count,
                share_percent=item.share_percent,
                top_style=item.top_style,
            )
            for item in payload.by_niche
        ],
        ai_recommendations=[
            StyleAiRecommendationResponse(
                code=item.code,
                priority=item.priority,
                message=item.message,
                niche_key=item.niche_key,
                selected_style=item.selected_style,
                slide_key=item.slide_key,
                metric=item.metric,
                estimated_lift_percent=item.estimated_lift_percent,
            )
            for item in payload.ai_recommendations
        ],
    )
