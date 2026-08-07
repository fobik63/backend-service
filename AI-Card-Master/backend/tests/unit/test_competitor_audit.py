"""Unit tests for competitor-link audit + Claude deep analysis (plan §77–78)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.competitor_audit_service import (
    CompetitorAuditService,
    CompetitorAuditValidationError,
)
from app.domain.competitor_audit import (
    ActionableBlueprint,
    CompetitorAuditEnqueueRequest,
    CompetitorAuditJobStatus,
    CompetitorAuditJobView,
    CompetitorAuditTransientError,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorProductLink,
    CompetitorReview,
    MarketGapVector,
    SemanticAuditVector,
    VisualAuditVector,
    assemble_deep_analysis_bundle,
    build_insufficient_card_analysis,
    card_has_sufficient_analysis_inputs,
    competitor_deep_analysis_system_prompt,
    normalize_deep_analysis_card,
    parse_competitor_product_link,
    redis_competitor_audit_key,
    split_reviews_by_rating,
)
from app.infrastructure.stock_parser.exceptions import ParserTransportError
from app.domain.stock_parser import ParserMarketplace


def test_parse_wildberries_catalog_link() -> None:
    link = parse_competitor_product_link(
        "https://www.wildberries.ru/catalog/123456789/detail.aspx"
    )
    assert link.marketplace is CompetitorMarketplace.WILDBERRIES
    assert link.article == "123456789"


def test_parse_ozon_product_link() -> None:
    link = parse_competitor_product_link(
        "https://www.ozon.ru/product/some-slug-987654321/"
    )
    assert link.marketplace is CompetitorMarketplace.OZON
    assert link.article == "987654321"


def test_reject_non_marketplace_host() -> None:
    with pytest.raises(ValueError, match="Only wildberries"):
        parse_competitor_product_link("https://example.com/product/123456")


def test_enqueue_request_max_three_links() -> None:
    with pytest.raises(ValidationError):
        CompetitorAuditEnqueueRequest(
            links=[
                "https://www.wildberries.ru/catalog/11111/detail.aspx",
                "https://www.wildberries.ru/catalog/22222/detail.aspx",
                "https://www.wildberries.ru/catalog/33333/detail.aspx",
                "https://www.wildberries.ru/catalog/44444/detail.aspx",
            ]
        )


def test_enqueue_request_rejects_duplicates() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        CompetitorAuditEnqueueRequest(
            links=[
                "https://www.wildberries.ru/catalog/11111/detail.aspx",
                "https://www.wildberries.ru/catalog/11111/detail.aspx",
            ]
        )


def test_split_reviews_by_rating_buckets() -> None:
    reviews = [
        CompetitorReview(rating=1, text="bad"),
        CompetitorReview(rating=3, text="meh"),
        CompetitorReview(rating=4, text="good"),
        CompetitorReview(rating=5, text="great"),
    ]
    low, high = split_reviews_by_rating(reviews)
    assert [r.rating for r in low] == [1, 3]
    assert [r.rating for r in high] == [4, 5]


def test_redis_key_shape() -> None:
    job_id = uuid4()
    assert redis_competitor_audit_key(job_id, "raw") == (
        f"analytics:competitor_audit:{job_id}:raw"
    )


def test_anti_hallucination_system_prompt() -> None:
    prompt = competitor_deep_analysis_system_prompt()
    assert "ANTI-HALLUCINATION" in prompt
    assert "insufficient_data" in prompt
    assert "NEVER invent" in prompt


def test_insufficient_card_when_empty_inputs() -> None:
    card = CompetitorCardScrapeResult(
        source_url="https://www.wildberries.ru/catalog/1/detail.aspx",
        marketplace=CompetitorMarketplace.WILDBERRIES,
        article="1",
        photo_urls=[],
        reviews_low=[],
        reviews_high=[],
        description="",
    )
    assert card_has_sufficient_analysis_inputs(card) is False
    analysis = build_insufficient_card_analysis(card, reason="no data")
    assert analysis.insufficient_data is True
    assert analysis.competitor_weaknesses == []
    assert "insufficient_data" in analysis.actionable_blueprint.generator_prompt


def test_normalize_deep_analysis_forces_article() -> None:
    card = CompetitorCardScrapeResult(
        source_url="https://www.wildberries.ru/catalog/999/detail.aspx",
        marketplace=CompetitorMarketplace.WILDBERRIES,
        article="999",
        title="Steel mug",
        photo_urls=["https://cdn.example/1.webp"],
        reviews_low=[CompetitorReview(rating=2, text="гнутся ручки")],
        reviews_high=[CompetitorReview(rating=5, text="красивый")],
    )
    raw = {
        "article": "HALLUCINATED",
        "marketplace": "ozon",
        "competitor_weaknesses": ["Photo shows steel, reviews say it bends"],
        "conversion_triggers": ["Large offer on first slide"],
        "actionable_blueprint": {
            "background": "Dark metal high contrast",
            "pain_badges": ["Does not bend"],
            "generator_prompt": "Beat the card with durability focus",
            "first_slide_offers": ["Rigidity guarantee"],
            "avoid_copying": ["Copy competitor font"],
        },
        "insufficient_data": False,
        "visual_audit": {
            "color_palette": ["#111", "#eee"],
            "first_slide_offer_layout": "offer left",
            "font_readability": "medium",
            "blind_zones": ["no seam macro"],
        },
        "semantic_audit": {
            "buyer_pains": ["handles bend"],
            "buyer_praise": ["looks nice"],
            "review_evidence_notes": [],
        },
        "market_gap": {
            "promise_vs_reality": ["Photo steel vs bends in reviews"],
            "exploitable_gaps": ["Show bend test"],
        },
        "confidence": 0.8,
        "reasoning_trace": "ok",
    }
    result = normalize_deep_analysis_card(raw, card=card)
    assert result.article == "999"
    assert result.marketplace == "wildberries"
    assert result.competitor_weaknesses[0].startswith("Photo shows steel")
    assert result.actionable_blueprint.pain_badges == ["Does not bend"]


def test_assemble_bundle_insufficient_when_all_cards_sparse() -> None:
    card = CompetitorCardScrapeResult(
        source_url="https://www.wildberries.ru/catalog/1/detail.aspx",
        marketplace=CompetitorMarketplace.WILDBERRIES,
        article="1",
    )
    a = build_insufficient_card_analysis(card, reason="sparse")
    bundle = assemble_deep_analysis_bundle([a], model_name="claude-opus-4-7")
    assert bundle.insufficient_data is True
    dumped = bundle.model_dump(mode="json")
    assert "competitor_weaknesses" in dumped["cards"][0]
    assert "conversion_triggers" in dumped["cards"][0]
    assert "actionable_blueprint" in dumped["cards"][0]


class _FakeRepo:
    def __init__(self) -> None:
        self.jobs: dict = {}

    async def create_job(self, *, user_id, links, idempotency_key=None):
        job = CompetitorAuditJobView(
            id=uuid4(),
            user_id=user_id,
            status=CompetitorAuditJobStatus.QUEUED,
            celery_task_id=None,
            links_payload=tuple(links),
            result_payload=None,
            analysis_payload=None,
            model_name=None,
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
        )
        self.jobs[job.id] = job
        return job

    async def find_idempotent_job(self, *, user_id, idempotency_key):
        return None

    async def get_job_for_user(self, *, user_id, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id):
        return self.jobs.get(job_id)

    async def mark_status(
        self,
        *,
        job_id,
        status,
        celery_task_id=None,
        error_message=None,
        completed_at=None,
    ):
        job = self.jobs[job_id]
        updated = CompetitorAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=status,
            celery_task_id=celery_task_id or job.celery_task_id,
            links_payload=job.links_payload,
            result_payload=job.result_payload,
            analysis_payload=job.analysis_payload,
            model_name=job.model_name,
            error_message=error_message if error_message is not None else job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at or job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_scrape_result(self, *, job_id, result_payload):
        job = self.jobs[job_id]
        updated = CompetitorAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=CompetitorAuditJobStatus.ANALYZING,
            celery_task_id=job.celery_task_id,
            links_payload=job.links_payload,
            result_payload=result_payload,
            analysis_payload=job.analysis_payload,
            model_name=job.model_name,
            error_message=None,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_analysis_result(
        self,
        *,
        job_id,
        analysis_payload,
        model_name,
        input_tokens_delta=0,
        output_tokens_delta=0,
    ):
        job = self.jobs[job_id]
        updated = CompetitorAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=CompetitorAuditJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            links_payload=job.links_payload,
            result_payload=job.result_payload,
            analysis_payload=analysis_payload,
            model_name=model_name,
            error_message=None,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated

    async def save_final_result(self, *, job_id, result_payload):
        job = self.jobs[job_id]
        updated = CompetitorAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=CompetitorAuditJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            links_payload=job.links_payload,
            result_payload=result_payload,
            analysis_payload=job.analysis_payload,
            model_name=job.model_name,
            error_message=None,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated


class _FakeScraper:
    def __init__(self, *, fail_transient: bool = False) -> None:
        self.fail_transient = fail_transient
        self.closed = False

    async def scrape_card(self, link: CompetitorProductLink) -> CompetitorCardScrapeResult:
        if self.fail_transient:
            raise ParserTransportError(
                "timeout",
                marketplace=ParserMarketplace.WILDBERRIES,
            )
        return CompetitorCardScrapeResult(
            source_url=link.url,
            marketplace=link.marketplace,
            article=link.article,
            title="Test",
            description="Full description",
            specs=[],
            photo_urls=["https://cdn.example/1.webp", "https://cdn.example/2.webp"],
            price_before_discount_kopecks=200_00,
            price_after_discount_kopecks=150_00,
            reviews_total_fetched=2,
            reviews_low=[CompetitorReview(rating=2, text="low")],
            reviews_high=[CompetitorReview(rating=5, text="high")],
            scrape_warnings=[],
            raw_fragments={"ok": True},
        )

    async def aclose(self) -> None:
        self.closed = True


class _FakeAnalyzer:
    model_name = "claude-opus-4-7"

    async def analyze_competitor_card(
        self, *, card, images, user_id=None, job_id=None
    ):
        result = CompetitorCardDeepAnalysis(
            article=card.article,
            marketplace=card.marketplace.value,
            title=card.title,
            competitor_weaknesses=["Слепая зона: нет макро шва"],
            conversion_triggers=["Яркий оффер на первом слайде"],
            actionable_blueprint=ActionableBlueprint(
                background="Контрастный тёмный фон",
                pain_badges=["Покажи шов крупно"],
                generator_prompt="Уничтожь карточку акцентом на прочность шва",
                first_slide_offers=["Гарантия 2 года"],
                avoid_copying=["Копировать их шрифт"],
            ),
            insufficient_data=False,
            visual_audit=VisualAuditVector(
                color_palette=["#000", "#fff"],
                first_slide_offer_layout="оффер сверху",
                font_readability="хорошая",
                blind_zones=["нет макро шва"],
            ),
            semantic_audit=SemanticAuditVector(
                buyer_pains=["low"],
                buyer_praise=["high"],
            ),
            market_gap=MarketGapVector(
                promise_vs_reality=[],
                exploitable_gaps=["макро шва"],
            ),
            confidence=0.9,
            reasoning_trace="evidence-based",
        )
        return result, 100, 50

    async def aclose(self) -> None:
        return None


class _FakeImages:
    async def fetch_urls(self, *, urls, max_images=5):
        return ((b"\xff\xd8\xfffake", "image/jpeg", urls[0]),)

    async def aclose(self) -> None:
        return None


class _FakeTrigger:
    def __init__(self) -> None:
        self.calls: list = []

    def enqueue_deep_analysis(self, *, job_id):
        self.calls.append(job_id)
        return "celery-task-id"


class _FakeStageCache:
    def __init__(self) -> None:
        self.store: dict[str, tuple[dict[str, Any], int]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        item = self.store.get(key)
        return None if item is None else item[0]

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        self.store[key] = (payload, ttl_seconds)


@pytest.mark.asyncio
async def test_service_enqueue_and_scrape() -> None:
    cache = _FakeStageCache()
    repo = _FakeRepo()
    scraper = _FakeScraper()
    trigger = _FakeTrigger()
    service = CompetitorAuditService(
        repo,
        scraper=scraper,
        redis_raw_ttl_seconds=3600,
        analysis_trigger=trigger,
        stage_cache=cache,
    )
    user_id = uuid4()
    request = CompetitorAuditEnqueueRequest(
        links=["https://www.wildberries.ru/catalog/55555555/detail.aspx"]
    )
    job, replay = await service.enqueue_audit(user_id=user_id, request=request)
    assert replay is False
    assert job.status is CompetitorAuditJobStatus.QUEUED

    finished = await service.run_scrape(job_id=job.id)
    assert finished.status is CompetitorAuditJobStatus.ANALYZING
    assert finished.result_payload is not None
    cards = finished.result_payload["cards"]
    assert len(cards) == 1
    assert cards[0]["photo_urls"] == [
        "https://cdn.example/1.webp",
        "https://cdn.example/2.webp",
    ]
    assert cards[0]["reviews_low"][0]["rating"] == 2
    assert cards[0]["reviews_high"][0]["rating"] == 5
    assert trigger.calls == [job.id]
    assert cache.store
    key, (payload, ttl) = next(iter(cache.store.items()))
    assert "analytics:competitor_audit:" in key
    assert ttl == 3600
    assert payload["status"] == "scraped"


@pytest.mark.asyncio
async def test_service_deep_analysis_returns_frontend_json() -> None:
    repo = _FakeRepo()
    trigger = _FakeTrigger()
    service = CompetitorAuditService(
        repo,
        scraper=_FakeScraper(),
        redis_raw_ttl_seconds=3600,
        analyzer=_FakeAnalyzer(),
        images=_FakeImages(),
        analysis_trigger=trigger,
        stage_cache=_FakeStageCache(),
    )
    user_id = uuid4()
    request = CompetitorAuditEnqueueRequest(
        links=["https://www.wildberries.ru/catalog/55555555/detail.aspx"]
    )
    job, _ = await service.enqueue_audit(user_id=user_id, request=request)
    await service.run_scrape(job_id=job.id)
    finished = await service.run_deep_analysis(job_id=job.id)

    assert finished.status is CompetitorAuditJobStatus.COMPLETED
    assert finished.analysis_payload is not None
    assert finished.analysis_payload["insufficient_data"] is False
    card = finished.analysis_payload["cards"][0]
    assert "competitor_weaknesses" in card
    assert "conversion_triggers" in card
    assert "actionable_blueprint" in card
    assert card["actionable_blueprint"]["background"]
    assert card["actionable_blueprint"]["pain_badges"]
    assert finished.input_tokens == 100
    assert finished.output_tokens == 50


@pytest.mark.asyncio
async def test_deep_analysis_without_claude_sets_insufficient_data() -> None:
    repo = _FakeRepo()
    service = CompetitorAuditService(
        repo,
        scraper=_FakeScraper(),
        redis_raw_ttl_seconds=3600,
        analyzer=None,
        analysis_trigger=_FakeTrigger(),
        stage_cache=_FakeStageCache(),
    )
    user_id = uuid4()
    request = CompetitorAuditEnqueueRequest(
        links=["https://www.wildberries.ru/catalog/55555555/detail.aspx"]
    )
    job, _ = await service.enqueue_audit(user_id=user_id, request=request)
    await service.run_scrape(job_id=job.id)
    finished = await service.run_deep_analysis(job_id=job.id)
    assert finished.status is CompetitorAuditJobStatus.COMPLETED
    assert finished.analysis_payload["insufficient_data"] is True
    assert finished.analysis_payload["cards"][0]["competitor_weaknesses"] == []


@pytest.mark.asyncio
async def test_service_raises_transient_on_timeout() -> None:
    repo = _FakeRepo()
    service = CompetitorAuditService(
        repo,
        scraper=_FakeScraper(fail_transient=True),
        redis_raw_ttl_seconds=3600,
        stage_cache=_FakeStageCache(),
    )
    user_id = uuid4()
    request = CompetitorAuditEnqueueRequest(
        links=["https://www.wildberries.ru/catalog/55555555/detail.aspx"]
    )
    job, _ = await service.enqueue_audit(user_id=user_id, request=request)

    with pytest.raises(CompetitorAuditTransientError):
        await service.run_scrape(job_id=job.id)


@pytest.mark.asyncio
async def test_enqueue_rejects_invalid_link() -> None:
    service = CompetitorAuditService(
        _FakeRepo(),
        scraper=_FakeScraper(),
        redis_raw_ttl_seconds=3600,
    )
    with pytest.raises((CompetitorAuditValidationError, ValidationError)):
        request = CompetitorAuditEnqueueRequest(
            links=["https://example.com/not-a-marketplace"]
        )
        await service.enqueue_audit(user_id=uuid4(), request=request)
