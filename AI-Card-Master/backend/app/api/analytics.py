"""Analytics API: style-preset insights + manual competitor-link audit."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.competitor_audit_service import (
    CompetitorAuditNotFoundError,
    CompetitorAuditService,
    CompetitorAuditValidationError,
)
from app.application.competitor_pains_llm_service import CompetitorPainsLlmService
from app.application.competitor_reviews_service import (
    CompetitorReviewsCollectionService,
    CompetitorReviewsUpstreamError,
    CompetitorReviewsValidationError,
)
from app.application.competitors_search_service import (
    CompetitorsSearchService,
    CompetitorsSearchUpstreamError,
    CompetitorsSearchValidationError,
)
from app.application.style_analytics_service import (
    StyleAnalyticsService,
    StyleAnalyticsValidationError,
    load_niche_titles_from_catalog,
)
from app.config.style_presets import load_style_presets
from app.domain.competitor_audit import (
    MAX_LINKS_PER_REQUEST,
    MAX_REVIEWS_PER_CARD,
    CompetitorAuditEnqueueRequest,
    CompetitorAuditJobStatus,
)
from app.domain.competitor_pains_llm import (
    MAX_PRODUCT_CONTEXT_LENGTH,
    CompetitorPainsAnalysisRequest,
    CompetitorPainsConfigurationError,
    CompetitorPainsLlmProvider,
    CompetitorPainsUpstreamError,
    CompetitorPainsValidationError,
)
from app.domain.competitor_reviews_collection import (
    MAX_ARTICLES,
    MAX_COMPLAINT_TEXTS,
    MIN_ARTICLES,
    CompetitorReviewsCollectionRequest,
)
from app.domain.competitors_search import (
    DEFAULT_COMPETITORS_LIMIT,
    MAX_COMPETITORS_LIMIT,
    MIN_COMPETITORS_LIMIT,
    MIN_QUERY_LENGTH,
    MAX_QUERY_LENGTH,
    CompetitorsSearchRequest,
)
from app.domain.eye_of_god_spy import (
    DEFAULT_TOP_COMPETITORS,
    MAX_TOP_COMPETITORS,
    MIN_TOP_COMPETITORS,
    EyeOfGodSpyEnqueueRequest,
)
from app.domain.style_analytics import InsightMetric, InsightPriority
from app.infrastructure.celery_app import celery_app
from app.infrastructure.competitor_audit_factory import build_competitor_audit_service
from app.infrastructure.competitor_pains_llm_factory import (
    build_competitor_pains_llm_service,
)
from app.infrastructure.competitor_reviews_factory import (
    build_competitor_reviews_service,
)
from app.infrastructure.competitors_search_factory import build_competitors_search_service
from app.infrastructure.persistence.style_analytics_repository import StyleAnalyticsRepository
from app.models.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
analytics_alias_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


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


class EyeOfGodSpyRequest(StrictAPIModel):
    """Spy analytics: competitor article/URL → discover TOP-N → deep audit."""

    input: str = Field(
        min_length=1,
        max_length=2048,
        description="Wildberries / Ozon product URL or numeric article.",
    )
    platform: Literal["auto", "wb", "ozon"] = "auto"
    limit: int = Field(
        default=DEFAULT_TOP_COMPETITORS,
        ge=MIN_TOP_COMPETITORS,
        le=MAX_TOP_COMPETITORS,
        description="How many TOP competitors to discover and audit (default 10).",
    )


class EyeOfGodSpyEnqueueResponse(StrictAPIModel):
    """HTTP 202 payload for Eye of God spy job."""

    task_id: UUID
    status: CompetitorAuditJobStatus
    status_url: str
    celery_task_id: str | None = None
    idempotent_replay: bool = False
    competitors_count: int = Field(ge=0, le=MAX_TOP_COMPETITORS)
    seed_title: str | None = None
    discovery: list[dict[str, Any]] = Field(default_factory=list)


class EyeOfGodSpyJobResponse(StrictAPIModel):
    """Poll response with scrape/analysis payloads + aggregated spy dashboard."""

    task_id: UUID
    status: CompetitorAuditJobStatus
    status_url: str
    links: list[str]
    celery_task_id: str | None = None
    result: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    dashboard: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Aggregated spy dashboard: badge_patterns, strong_triggers, "
            "frequent_keywords, visual_hooks, ai_recommendation, generator_prompt."
        ),
    )
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_message: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class CompetitorsSearchBody(StrictAPIModel):
    """Keyword search for TOP-N Wildberries competitor cards."""

    query: str = Field(
        min_length=MIN_QUERY_LENGTH,
        max_length=MAX_QUERY_LENGTH,
        description='Keyword query, e.g. "крем для рук увлажняющий".',
    )
    limit: int = Field(
        default=DEFAULT_COMPETITORS_LIMIT,
        ge=MIN_COMPETITORS_LIMIT,
        le=MAX_COMPETITORS_LIMIT,
        description="How many TOP competitors to return (default 10).",
    )


class CompetitorCardResponse(StrictAPIModel):
    """One competitor card from WB search SERP."""

    rank: int = Field(ge=1, le=MAX_COMPETITORS_LIMIT)
    article: str
    title: str | None = None
    brand: str | None = None
    price_rub: float | None = None
    rating: float | None = None
    feedbacks: int | None = None
    url: str
    estimated_purchases: int | None = Field(
        default=None,
        description="Heuristic: feedbacks × ~12.5 (until MPSTATS/MarketGuru).",
    )
    estimated_revenue_rub: float | None = Field(
        default=None,
        description="Оценочная выручка: estimated_purchases × price_rub.",
    )


class CompetitorsSearchResponse(StrictAPIModel):
    """TOP-N competitor cards: article, price, rating, feedbacks."""

    query: str
    count: int = Field(ge=0, le=MAX_COMPETITORS_LIMIT)
    competitors: list[CompetitorCardResponse]


class CompetitorReviewsCollectionBody(StrictAPIModel):
    """Collect 1–3★ complaint texts for TOP-N competitor nm_ids."""

    articles: list[str] = Field(
        min_length=MIN_ARTICLES,
        max_length=MAX_ARTICLES,
        description="nm_id list from TOP-10 competitors search.",
    )
    max_reviews_per_article: int = Field(
        default=MAX_REVIEWS_PER_CARD,
        ge=1,
        le=MAX_REVIEWS_PER_CARD,
    )


class CompetitorArticleReviewsResponse(StrictAPIModel):
    """Per-competitor harvest summary."""

    article: str
    reviews_fetched: int = Field(ge=0)
    complaint_texts: list[str]
    warning: str | None = None


class CompetitorReviewsCollectionResponse(StrictAPIModel):
    """Unified complaint-text corpus for downstream pain analysis."""

    articles: list[str]
    competitors_processed: int = Field(ge=0, le=MAX_ARTICLES)
    reviews_fetched: int = Field(ge=0)
    complaint_texts: list[str] = Field(
        description=(
            'Flat list of complaint strings, e.g. "жидкий", "плохо пахнет".'
        ),
        max_length=MAX_COMPLAINT_TEXTS,
    )
    by_article: list[CompetitorArticleReviewsResponse]
    warnings: list[str] = Field(default_factory=list)


class CompetitorPainsAnalyzeBody(StrictAPIModel):
    """POST body: complaint corpus from ``/competitors/reviews``."""

    complaint_texts: list[str] = Field(
        min_length=1,
        max_length=MAX_COMPLAINT_TEXTS,
        description="Negative review complaint strings from competitor cards.",
    )
    product_context: str = Field(
        default="",
        max_length=MAX_PRODUCT_CONTEXT_LENGTH,
        description="Optional brief about OUR product to tailor offers.",
    )


class BuyerPainResponse(StrictAPIModel):
    rank: int = Field(ge=1, le=3)
    title: str
    summary: str
    evidence_quotes: list[str] = Field(default_factory=list)


class InfographicOfferResponse(StrictAPIModel):
    pain_rank: int = Field(ge=1, le=3)
    offer_text: str


class CompetitorPainsAnalysisResponse(StrictAPIModel):
    """Structured LLM JSON: 3 buyer pains + matching infographic offers."""

    pains: list[BuyerPainResponse]
    recommendations: list[InfographicOfferResponse]
    provider: CompetitorPainsLlmProvider
    model_name: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


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


async def get_competitors_search_service() -> AsyncIterator[CompetitorsSearchService]:
    """Request-scoped WB keyword competitor search (closes HTTP transport)."""

    service = build_competitors_search_service()
    try:
        yield service
    finally:
        await service.aclose()


async def get_competitor_reviews_service() -> AsyncIterator[
    CompetitorReviewsCollectionService
]:
    """Request-scoped WB low-rating reviews collector (closes HTTP transport)."""

    service = build_competitor_reviews_service()
    try:
        yield service
    finally:
        await service.aclose()


async def get_competitor_pains_llm_service() -> AsyncIterator[CompetitorPainsLlmService]:
    """Request-scoped OpenAI / local-Ollama competitor pains analyzer."""

    try:
        service = build_competitor_pains_llm_service()
    except CompetitorPainsConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    try:
        yield service
    finally:
        await service.aclose()


def _competitors_search_response(result) -> CompetitorsSearchResponse:
    return CompetitorsSearchResponse(
        query=result.query,
        count=result.count,
        competitors=[
            CompetitorCardResponse(
                rank=card.rank,
                article=card.article,
                title=card.title,
                brand=card.brand,
                price_rub=card.price_rub,
                rating=card.rating,
                feedbacks=card.feedbacks,
                url=card.url,
                estimated_purchases=card.estimated_purchases,
                estimated_revenue_rub=card.estimated_revenue_rub,
            )
            for card in result.competitors
        ],
    )


async def _run_competitors_search(
    *,
    query: str,
    limit: int,
    service: CompetitorsSearchService,
) -> CompetitorsSearchResponse:
    try:
        request = CompetitorsSearchRequest(query=query, limit=limit)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        result = await service.search(request)
    except CompetitorsSearchValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except CompetitorsSearchUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _competitors_search_response(result)


def _competitor_reviews_response(result) -> CompetitorReviewsCollectionResponse:
    return CompetitorReviewsCollectionResponse(
        articles=list(result.articles),
        competitors_processed=result.competitors_processed,
        reviews_fetched=result.reviews_fetched,
        complaint_texts=list(result.complaint_texts),
        by_article=[
            CompetitorArticleReviewsResponse(
                article=item.article,
                reviews_fetched=item.reviews_fetched,
                complaint_texts=list(item.complaint_texts),
                warning=item.warning,
            )
            for item in result.by_article
        ],
        warnings=list(result.warnings),
    )


async def _run_competitor_reviews_collection(
    *,
    articles: list[str],
    max_reviews_per_article: int,
    service: CompetitorReviewsCollectionService,
) -> CompetitorReviewsCollectionResponse:
    try:
        request = CompetitorReviewsCollectionRequest(
            articles=articles,
            max_reviews_per_article=max_reviews_per_article,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        result = await service.collect_complaint_texts(request)
    except CompetitorReviewsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except CompetitorReviewsUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _competitor_reviews_response(result)


def _competitor_pains_response(result) -> CompetitorPainsAnalysisResponse:
    return CompetitorPainsAnalysisResponse(
        pains=[
            BuyerPainResponse(
                rank=item.rank,
                title=item.title,
                summary=item.summary,
                evidence_quotes=list(item.evidence_quotes),
            )
            for item in result.pains
        ],
        recommendations=[
            InfographicOfferResponse(
                pain_rank=item.pain_rank,
                offer_text=item.offer_text,
            )
            for item in result.recommendations
        ],
        provider=result.provider,
        model_name=result.model_name,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


async def _run_competitor_pains_analysis(
    *,
    complaint_texts: list[str],
    product_context: str,
    service: CompetitorPainsLlmService,
) -> CompetitorPainsAnalysisResponse:
    try:
        request = CompetitorPainsAnalysisRequest(
            complaint_texts=complaint_texts,
            product_context=product_context,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        result = await service.analyze_negative_reviews(request)
    except CompetitorPainsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except CompetitorPainsConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CompetitorPainsUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _competitor_pains_response(result)


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


@router.post(
    "/eye-of-god",
    response_model=EyeOfGodSpyEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Eye of God: discover TOP competitors by article and enqueue deep audit",
)
async def enqueue_eye_of_god_spy(
    body: EyeOfGodSpyRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    service: CompetitorAuditService = Depends(get_competitor_audit_service),
) -> EyeOfGodSpyEnqueueResponse:
    """Resolve competitor article/URL, find TOP-N similar cards, enqueue scrape+Claude."""

    try:
        request = EyeOfGodSpyEnqueueRequest(
            input=body.input,
            platform=body.platform,
            limit=body.limit,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        job, replay, hits, seed_title = await service.enqueue_eye_of_god_spy(
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

    return EyeOfGodSpyEnqueueResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/analytics/eye-of-god/{job.id}",
        celery_task_id=celery_task_id,
        idempotent_replay=replay,
        competitors_count=len(hits) if hits else len(job.links_payload),
        seed_title=seed_title,
        discovery=[hit.model_dump(mode="json") for hit in hits],
    )


@router.get(
    "/eye-of-god/{task_id}",
    response_model=EyeOfGodSpyJobResponse,
    summary="Poll Eye of God spy job (scrape + Claude + dashboard)",
)
async def get_eye_of_god_spy_job(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CompetitorAuditService = Depends(get_competitor_audit_service),
) -> EyeOfGodSpyJobResponse:
    """Return scrape/analysis status and aggregated spy dashboard when ready."""

    try:
        job = await service.get_job_for_user(user_id=current_user.id, job_id=task_id)
    except CompetitorAuditNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    dashboard = None
    if job.status == CompetitorAuditJobStatus.COMPLETED or job.analysis_payload:
        built = await service.build_spy_dashboard_async(job)
        if built is not None:
            dashboard = built.model_dump(mode="json")

    return EyeOfGodSpyJobResponse(
        task_id=job.id,
        status=job.status,
        status_url=f"/api/v1/analytics/eye-of-god/{job.id}",
        links=list(job.links_payload),
        celery_task_id=job.celery_task_id,
        result=job.result_payload,
        analysis=job.analysis_payload,
        dashboard=dashboard,
        model_name=job.model_name,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
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


@router.post(
    "/competitors",
    response_model=CompetitorsSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="TOP-10 WB competitors by keyword (search.wb.ru)",
)
async def search_competitors(
    body: CompetitorsSearchBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorsSearchService = Depends(get_competitors_search_service),
) -> CompetitorsSearchResponse:
    """Search Wildberries catalog and return TOP-N competitor cards.

    Uses ``https://search.wb.ru/exactmatch/ru/common/v7/search`` (fallback v5)
    and returns article, price, rating, and feedback count for each hit.
    """

    _ = current_user
    return await _run_competitors_search(
        query=body.query,
        limit=body.limit,
        service=service,
    )


@router.get(
    "/competitors",
    response_model=CompetitorsSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="TOP-10 WB competitors by keyword (GET)",
)
async def search_competitors_get(
    query: str = Query(
        ...,
        min_length=MIN_QUERY_LENGTH,
        max_length=MAX_QUERY_LENGTH,
        description='Keyword query, e.g. "крем для рук увлажняющий".',
    ),
    limit: int = Query(
        default=DEFAULT_COMPETITORS_LIMIT,
        ge=MIN_COMPETITORS_LIMIT,
        le=MAX_COMPETITORS_LIMIT,
    ),
    current_user: User = Depends(get_current_user),
    service: CompetitorsSearchService = Depends(get_competitors_search_service),
) -> CompetitorsSearchResponse:
    """GET variant of keyword competitor search."""

    _ = current_user
    return await _run_competitors_search(
        query=query,
        limit=limit,
        service=service,
    )


@router.post(
    "/competitors/reviews",
    response_model=CompetitorReviewsCollectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Collect 1–3★ complaint texts for TOP-N competitors",
)
async def collect_competitor_reviews(
    body: CompetitorReviewsCollectionBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorReviewsCollectionService = Depends(
        get_competitor_reviews_service
    ),
) -> CompetitorReviewsCollectionResponse:
    """Asynchronously fetch low-rating reviews for TOP-10 competitor nm_ids.

    Focuses on 1–3★ feedbacks and returns a flat ``complaint_texts`` array
    (e.g. "жидкий", "плохо пахнет") for downstream pain analysis.
    """

    _ = current_user
    return await _run_competitor_reviews_collection(
        articles=body.articles,
        max_reviews_per_article=body.max_reviews_per_article,
        service=service,
    )


@analytics_alias_router.post(
    "/competitors/reviews",
    response_model=CompetitorReviewsCollectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Collect 1–3★ complaint texts (alias)",
    description="Alias of ``POST /api/v1/analytics/competitors/reviews``.",
)
async def collect_competitor_reviews_alias(
    body: CompetitorReviewsCollectionBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorReviewsCollectionService = Depends(
        get_competitor_reviews_service
    ),
) -> CompetitorReviewsCollectionResponse:
    _ = current_user
    return await _run_competitor_reviews_collection(
        articles=body.articles,
        max_reviews_per_article=body.max_reviews_per_article,
        service=service,
    )


@router.post(
    "/competitors/reviews/analyze",
    response_model=CompetitorPainsAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="LLM: 3 competitor pains + infographic offers",
)
async def analyze_competitor_negative_reviews(
    body: CompetitorPainsAnalyzeBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorPainsLlmService = Depends(get_competitor_pains_llm_service),
) -> CompetitorPainsAnalysisResponse:
    """Send collected competitor complaint texts to OpenAI or local Ollama (GPU).

    System prompt: marketplace analyst → 3 main buyer pains + concrete
    infographic offer texts for OUR card. Returns structured JSON.
    """

    _ = current_user
    return await _run_competitor_pains_analysis(
        complaint_texts=body.complaint_texts,
        product_context=body.product_context,
        service=service,
    )


@analytics_alias_router.post(
    "/competitors/reviews/analyze",
    response_model=CompetitorPainsAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="LLM: 3 competitor pains + offers (alias)",
    description="Alias of ``POST /api/v1/analytics/competitors/reviews/analyze``.",
)
async def analyze_competitor_negative_reviews_alias(
    body: CompetitorPainsAnalyzeBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorPainsLlmService = Depends(get_competitor_pains_llm_service),
) -> CompetitorPainsAnalysisResponse:
    _ = current_user
    return await _run_competitor_pains_analysis(
        complaint_texts=body.complaint_texts,
        product_context=body.product_context,
        service=service,
    )


@analytics_alias_router.post(
    "/competitors",
    response_model=CompetitorsSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="TOP-10 WB competitors by keyword (alias)",
    description="Alias of ``POST /api/v1/analytics/competitors``.",
)
async def search_competitors_alias(
    body: CompetitorsSearchBody,
    current_user: User = Depends(get_current_user),
    service: CompetitorsSearchService = Depends(get_competitors_search_service),
) -> CompetitorsSearchResponse:
    _ = current_user
    return await _run_competitors_search(
        query=body.query,
        limit=body.limit,
        service=service,
    )


@analytics_alias_router.get(
    "/competitors",
    response_model=CompetitorsSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="TOP-10 WB competitors by keyword (GET alias)",
    description="Alias of ``GET /api/v1/analytics/competitors``.",
)
async def search_competitors_get_alias(
    query: str = Query(
        ...,
        min_length=MIN_QUERY_LENGTH,
        max_length=MAX_QUERY_LENGTH,
        description='Keyword query, e.g. "крем для рук увлажняющий".',
    ),
    limit: int = Query(
        default=DEFAULT_COMPETITORS_LIMIT,
        ge=MIN_COMPETITORS_LIMIT,
        le=MAX_COMPETITORS_LIMIT,
    ),
    current_user: User = Depends(get_current_user),
    service: CompetitorsSearchService = Depends(get_competitors_search_service),
) -> CompetitorsSearchResponse:
    _ = current_user
    return await _run_competitors_search(
        query=query,
        limit=limit,
        service=service,
    )
