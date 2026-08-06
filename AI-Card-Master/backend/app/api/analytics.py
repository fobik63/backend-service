"""Style-preset analytics API: popularity tracking and AI insights."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.style_analytics_service import (
    StyleAnalyticsService,
    StyleAnalyticsValidationError,
    load_niche_titles_from_catalog,
)
from app.config.style_presets import load_style_presets
from app.domain.style_analytics import InsightMetric, InsightPriority
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
