"""Manual competitor-card audit: deep scrape + Claude deep analysis (plan §77–78).

Pipeline:
1. Validate ≤3 marketplace product links (strict hosts / path shape).
2. Enqueue Celery job → HTTP 202 with durable task_id.
3. Deep-scrape each link: gallery photos, description, specs, prices, 50 reviews.
4. Split reviews into 1–3★ vs 4–5★ buckets.
5. Cache raw parse log in Redis (TTL 1 hour).
6. Immediately after scrape: Claude 4.7 Opus Vision + reviews → strict frontend JSON
   (competitor_weaknesses / conversion_triggers / actionable_blueprint).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


MAX_LINKS_PER_REQUEST = 3
MAX_REVIEWS_PER_CARD = 50
REDIS_RAW_LOG_TTL_SECONDS = 3600
MAX_VISION_IMAGES_PER_CARD = 5
MAX_REVIEW_TEXTS_IN_PROMPT = 40

_WB_HOSTS = frozenset(
    {
        "www.wildberries.ru",
        "wildberries.ru",
        "global.wildberries.ru",
        "www.wb.ru",
        "wb.ru",
    }
)
_OZON_HOSTS = frozenset(
    {
        "www.ozon.ru",
        "ozon.ru",
        "m.ozon.ru",
    }
)
_WB_CATALOG_PATH = re.compile(r"/catalog/(\d{5,})", re.IGNORECASE)
_OZON_PRODUCT_PATH = re.compile(r"/product/[^/]*?(\d{6,})", re.IGNORECASE)


class CompetitorAuditJobStatus(StrEnum):
    """Lifecycle of an async competitor-link audit (scrape → Claude deep analysis)."""

    QUEUED = "queued"
    SCRAPING = "scraping"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class CompetitorMarketplace(StrEnum):
    """Supported public marketplaces for manual audit links."""

    WILDBERRIES = "wildberries"
    OZON = "ozon"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for competitor-audit request validation."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PersistedDomainModel(BaseModel):
    """JSONB-roundtrip-safe models (enum/str coercion allowed)."""

    model_config = ConfigDict(extra="forbid")


class CompetitorAuditTransientError(Exception):
    """Timeout / captcha / rate-limit — Celery must retry."""


class CompetitorAuditPermanentError(Exception):
    """Invalid payload or non-retryable scrape failure."""


class CompetitorProductLink(StrictDomainModel):
    """One validated WB or Ozon product URL with resolved marketplace + article."""

    url: str = Field(min_length=12, max_length=2048)
    marketplace: CompetitorMarketplace
    article: str = Field(min_length=1, max_length=64)

    @field_validator("url", mode="before")
    @classmethod
    def _strip_url(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CompetitorAuditEnqueueRequest(StrictDomainModel):
    """API/domain request: 1–3 competitor product links."""

    links: list[str] = Field(min_length=1, max_length=MAX_LINKS_PER_REQUEST)

    @field_validator("links", mode="before")
    @classmethod
    def _normalize_links(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("links must be an array of URL strings.")
        if len(value) > MAX_LINKS_PER_REQUEST:
            raise ValueError(
                f"At most {MAX_LINKS_PER_REQUEST} links are allowed per request."
            )
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Each link must be a string URL.")
            url = item.strip()
            if not url:
                raise ValueError("Empty link strings are not allowed.")
            if len(url) > 2048:
                raise ValueError("Link exceeds maximum length of 2048 characters.")
            key = url.casefold()
            if key in seen:
                raise ValueError("Duplicate links are not allowed in one request.")
            seen.add(key)
            cleaned.append(url)
        if not cleaned:
            raise ValueError("At least one link is required.")
        return cleaned

    @model_validator(mode="after")
    def _validate_marketplace_urls(self) -> CompetitorAuditEnqueueRequest:
        # Force parse+validate every link early (API 422 before enqueue).
        for url in self.links:
            parse_competitor_product_link(url)
        return self

    def parsed_links(self) -> tuple[CompetitorProductLink, ...]:
        return tuple(parse_competitor_product_link(url) for url in self.links)


class CompetitorReview(PersistedDomainModel):
    """One marketplace review with star rating."""

    review_id: str | None = Field(default=None, max_length=128)
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=8000)
    author: str | None = Field(default=None, max_length=256)
    created_at: str | None = Field(default=None, max_length=64)
    pros: str | None = Field(default=None, max_length=4000)
    cons: str | None = Field(default=None, max_length=4000)


class CompetitorSpecRow(PersistedDomainModel):
    """One row from the product characteristics table."""

    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=2000)


class CompetitorCardScrapeResult(PersistedDomainModel):
    """Deep raw scrape for one competitor card (task 77 depth)."""

    source_url: str = Field(min_length=1, max_length=2048)
    marketplace: CompetitorMarketplace
    article: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    description: str = Field(default="", max_length=50_000)
    specs: list[CompetitorSpecRow] = Field(default_factory=list, max_length=200)
    photo_urls: list[str] = Field(default_factory=list, max_length=100)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    price_after_discount_kopecks: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    reviews_total_fetched: int = Field(default=0, ge=0, le=MAX_REVIEWS_PER_CARD)
    reviews_low: list[CompetitorReview] = Field(
        default_factory=list,
        max_length=MAX_REVIEWS_PER_CARD,
        description="Reviews rated 1–3 stars.",
    )
    reviews_high: list[CompetitorReview] = Field(
        default_factory=list,
        max_length=MAX_REVIEWS_PER_CARD,
        description="Reviews rated 4–5 stars.",
    )
    scrape_warnings: list[str] = Field(default_factory=list, max_length=40)
    raw_fragments: dict[str, Any] = Field(
        default_factory=dict,
        description="Truncated raw marketplace JSON fragments for Redis log.",
    )


class CompetitorAuditResult(PersistedDomainModel):
    """Aggregated scrape result for all links in a job."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    cards: list[CompetitorCardScrapeResult] = Field(
        default_factory=list,
        max_length=MAX_LINKS_PER_REQUEST,
    )
    parse_log: list[str] = Field(default_factory=list, max_length=200)


@dataclass(frozen=True, slots=True)
class CompetitorAuditJobView:
    """Projection of a persisted competitor-audit job."""

    id: UUID
    user_id: UUID
    status: CompetitorAuditJobStatus
    celery_task_id: str | None
    links_payload: tuple[str, ...]
    result_payload: dict[str, Any] | None
    analysis_payload: dict[str, Any] | None
    model_name: str | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


# ---------------------------------------------------------------------------
# Plan §78 — deep Claude 4.7 Opus analysis (Vision + reviews → frontend JSON)
# ---------------------------------------------------------------------------


class VisualAuditVector(PersistedDomainModel):
    """Vector 1: visual audit of competitor card photos (first slide focus)."""

    color_palette: list[str] = Field(default_factory=list, max_length=12)
    first_slide_offer_layout: str = Field(default="", max_length=800)
    font_readability: str = Field(default="", max_length=500)
    blind_zones: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="What the competitor forgot to show on the card.",
    )


class SemanticAuditVector(PersistedDomainModel):
    """Vector 2: real buyer pains (negatives) and praise (positives)."""

    buyer_pains: list[str] = Field(default_factory=list, max_length=12)
    buyer_praise: list[str] = Field(default_factory=list, max_length=12)
    review_evidence_notes: list[str] = Field(default_factory=list, max_length=12)


class MarketGapVector(PersistedDomainModel):
    """Vector 3: strategic gap between visual promises and review reality."""

    promise_vs_reality: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "E.g. 'На фото сталь, а в отзывах пишут, что гнется'."
        ),
    )
    exploitable_gaps: list[str] = Field(default_factory=list, max_length=12)


class ActionableBlueprint(PersistedDomainModel):
    """Concrete TZ/prompt for our generator to outcompete this card."""

    background: str = Field(
        min_length=1,
        max_length=800,
        description="Which background / atmosphere to set.",
    )
    pain_badges: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Pain hooks to place on first-slide badges.",
    )
    generator_prompt: str = Field(
        min_length=1,
        max_length=4000,
        description="Ready-to-use prompt / TZ for the image generator.",
    )
    first_slide_offers: list[str] = Field(default_factory=list, max_length=8)
    avoid_copying: list[str] = Field(default_factory=list, max_length=8)


class CompetitorCardDeepAnalysis(PersistedDomainModel):
    """Strict per-card JSON for the frontend (plan §78 CRITICAL 2)."""

    article: str = Field(min_length=1, max_length=64)
    marketplace: str = Field(min_length=1, max_length=32)
    title: str | None = Field(default=None, max_length=500)
    competitor_weaknesses: list[str] = Field(default_factory=list, max_length=20)
    conversion_triggers: list[str] = Field(default_factory=list, max_length=20)
    actionable_blueprint: ActionableBlueprint
    insufficient_data: bool = False
    visual_audit: VisualAuditVector = Field(default_factory=VisualAuditVector)
    semantic_audit: SemanticAuditVector = Field(default_factory=SemanticAuditVector)
    market_gap: MarketGapVector = Field(default_factory=MarketGapVector)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_trace: str = Field(default="", max_length=4000)

    @field_validator(
        "competitor_weaknesses",
        "conversion_triggers",
        mode="before",
    )
    @classmethod
    def _clean_str_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("List items must be strings.")
            text = re.sub(r"\s+", " ", item.strip())
            if text:
                cleaned.append(text)
        return cleaned


class CompetitorDeepAnalysisBundle(PersistedDomainModel):
    """Job-level analysis payload returned to the frontend poll endpoint."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    cards: list[CompetitorCardDeepAnalysis] = Field(
        default_factory=list,
        max_length=MAX_LINKS_PER_REQUEST,
    )
    insufficient_data: bool = False
    model_name: str = Field(default="claude-opus-4-7", min_length=1, max_length=128)
    notes: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _sync_insufficient_flag(self) -> CompetitorDeepAnalysisBundle:
        if self.cards and all(card.insufficient_data for card in self.cards):
            self.insufficient_data = True
        return self


# Claude structured-output schema (strict JSON Mode).
COMPETITOR_DEEP_ANALYSIS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "article",
        "marketplace",
        "competitor_weaknesses",
        "conversion_triggers",
        "actionable_blueprint",
        "insufficient_data",
        "visual_audit",
        "semantic_audit",
        "market_gap",
        "confidence",
        "reasoning_trace",
    ],
    "properties": {
        "article": {"type": "string"},
        "marketplace": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "competitor_weaknesses": {
            "type": "array",
            "items": {"type": "string"},
        },
        "conversion_triggers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "actionable_blueprint": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "background",
                "pain_badges",
                "generator_prompt",
                "first_slide_offers",
                "avoid_copying",
            ],
            "properties": {
                "background": {"type": "string"},
                "pain_badges": {"type": "array", "items": {"type": "string"}},
                "generator_prompt": {"type": "string"},
                "first_slide_offers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "avoid_copying": {"type": "array", "items": {"type": "string"}},
            },
        },
        "insufficient_data": {"type": "boolean"},
        "visual_audit": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "color_palette",
                "first_slide_offer_layout",
                "font_readability",
                "blind_zones",
            ],
            "properties": {
                "color_palette": {"type": "array", "items": {"type": "string"}},
                "first_slide_offer_layout": {"type": "string"},
                "font_readability": {"type": "string"},
                "blind_zones": {"type": "array", "items": {"type": "string"}},
            },
        },
        "semantic_audit": {
            "type": "object",
            "additionalProperties": False,
            "required": ["buyer_pains", "buyer_praise", "review_evidence_notes"],
            "properties": {
                "buyer_pains": {"type": "array", "items": {"type": "string"}},
                "buyer_praise": {"type": "array", "items": {"type": "string"}},
                "review_evidence_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "market_gap": {
            "type": "object",
            "additionalProperties": False,
            "required": ["promise_vs_reality", "exploitable_gaps"],
            "properties": {
                "promise_vs_reality": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "exploitable_gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number"},
        "reasoning_trace": {"type": "string"},
    },
}


_COMPETITOR_DEEP_ANALYSIS_SYSTEM_PROMPT = (
    "You are a senior marketplace conversion auditor for Wildberries / Ozon. "
    "You receive competitor card PHOTOS (Vision) plus product text and reviews. "
    "Perform a THREE-VECTOR audit:\n"
    "1) Visual audit: color palette, offer placement on the FIRST slide, "
    "font readability, and blind zones (what the competitor forgot to show).\n"
    "2) Semantic audit (reviews): extract REAL buyer pains from 1–3★ reviews "
    "and what buyers genuinely praise in 4–5★ reviews. Ignore delivery/warehouse "
    "noise and empty emotional rants without product facts.\n"
    "3) Strategic Market Gap: compare visual promises vs review reality "
    "(e.g. 'На фото сталь, а в отзывах пишут, что гнется').\n"
    "Return ONLY valid JSON matching the schema with fields: "
    "competitor_weaknesses, conversion_triggers, actionable_blueprint "
    "(background, pain_badges, generator_prompt — concrete TZ to beat this card).\n"
    "ANTI-HALLUCINATION (CRITICAL): NEVER invent problems that are not visible "
    "in the photos or explicitly stated in the provided reviews. "
    "If the card is strong / nearly ideal, return empty competitor_weaknesses "
    "and still list real conversion_triggers. "
    "If photos or reviews are missing / too sparse to judge, set "
    "insufficient_data=true and keep speculative fields empty. "
    "Do not fabricate review quotes or visual elements."
)


def competitor_deep_analysis_system_prompt() -> str:
    return _COMPETITOR_DEEP_ANALYSIS_SYSTEM_PROMPT


def build_competitor_deep_analysis_prompt(
    *,
    card: CompetitorCardScrapeResult,
    image_count: int,
) -> str:
    """User prompt: text context for reviews/specs + Vision images already attached."""

    low_texts = _review_texts_for_prompt(card.reviews_low)
    high_texts = _review_texts_for_prompt(card.reviews_high)
    specs_lines = [
        f"- {row.name}: {row.value}" for row in card.specs[:40]
    ]
    price_before = _kopecks_to_rub(card.price_before_discount_kopecks)
    price_after = _kopecks_to_rub(card.price_after_discount_kopecks)
    title = (card.title or card.article).strip()

    return (
        f"Аудит карточки конкурента.\n"
        f"article={card.article}\n"
        f"marketplace={card.marketplace.value}\n"
        f"title={title}\n"
        f"price_before_rub={price_before}\n"
        f"price_after_rub={price_after}\n"
        f"images_attached={image_count} (первое = главный слайд)\n"
        f"description:\n{(card.description or '')[:6000]}\n"
        f"specs:\n" + ("\n".join(specs_lines) if specs_lines else "(нет)") + "\n"
        f"reviews_low_1_3_stars ({len(card.reviews_low)}):\n"
        + ("\n---\n".join(low_texts) if low_texts else "(нет негативных)")
        + "\n"
        f"reviews_high_4_5_stars ({len(card.reviews_high)}):\n"
        + ("\n---\n".join(high_texts) if high_texts else "(нет позитивных)")
        + "\n"
        "Проведи трёхвекторный аудит. "
        "Поле article в ответе должно быть ровно: "
        f"{card.article}. "
        "Поле marketplace: "
        f"{card.marketplace.value}. "
        "Сначала reasoning_trace, затем заполняй JSON."
    )


def card_has_sufficient_analysis_inputs(card: CompetitorCardScrapeResult) -> bool:
    """True when at least one photo URL or one non-empty review exists."""

    if any(url.strip() for url in card.photo_urls):
        return True
    for review in (*card.reviews_low, *card.reviews_high):
        if (review.text or "").strip() or (review.pros or "").strip() or (
            review.cons or ""
        ).strip():
            return True
    if (card.description or "").strip():
        return True
    return False


def build_insufficient_card_analysis(
    card: CompetitorCardScrapeResult,
    *,
    reason: str,
) -> CompetitorCardDeepAnalysis:
    """Safe frontend payload when data is too sparse to audit."""

    return CompetitorCardDeepAnalysis(
        article=card.article,
        marketplace=card.marketplace.value,
        title=card.title,
        competitor_weaknesses=[],
        conversion_triggers=[],
        actionable_blueprint=ActionableBlueprint(
            background=(
                "Недостаточно данных для рекомендации фона — "
                "сначала соберите фото/отзывы конкурента."
            ),
            pain_badges=[],
            generator_prompt=(
                "insufficient_data: не генерируй атаку на карточку без "
                f"подтверждённых фактов. Причина: {reason}"
            ),
            first_slide_offers=[],
            avoid_copying=[],
        ),
        insufficient_data=True,
        visual_audit=VisualAuditVector(),
        semantic_audit=SemanticAuditVector(),
        market_gap=MarketGapVector(),
        confidence=0.0,
        reasoning_trace=reason[:4000],
    )


def normalize_deep_analysis_card(
    payload: dict[str, Any],
    *,
    card: CompetitorCardScrapeResult,
) -> CompetitorCardDeepAnalysis:
    """Validate Claude JSON and force article/marketplace from scrape truth."""

    merged = dict(payload)
    merged["article"] = card.article
    merged["marketplace"] = card.marketplace.value
    if not merged.get("title"):
        merged["title"] = card.title

    insufficient = bool(merged.get("insufficient_data"))
    blueprint = merged.get("actionable_blueprint")
    if not isinstance(blueprint, dict):
        if insufficient:
            blueprint = {}
            merged["actionable_blueprint"] = blueprint
        else:
            raise ValueError("actionable_blueprint must be an object.")

    if insufficient:
        blueprint.setdefault(
            "background",
            "Недостаточно данных — не задавайте агрессивный фон без фактов.",
        )
        blueprint.setdefault(
            "generator_prompt",
            "insufficient_data: не выдумывай слабости конкурента.",
        )
        blueprint.setdefault("pain_badges", [])
        blueprint.setdefault("first_slide_offers", [])
        blueprint.setdefault("avoid_copying", [])
        merged["actionable_blueprint"] = blueprint
        merged.setdefault("competitor_weaknesses", [])
        merged.setdefault("conversion_triggers", [])
    else:
        for key in ("background", "generator_prompt"):
            if not str(blueprint.get(key) or "").strip():
                raise ValueError(f"actionable_blueprint.{key} is required.")

    return CompetitorCardDeepAnalysis.model_validate(merged)


def dump_deep_analysis_bundle(bundle: CompetitorDeepAnalysisBundle) -> dict[str, Any]:
    return bundle.model_dump(mode="json")


def assemble_deep_analysis_bundle(
    cards: list[CompetitorCardDeepAnalysis],
    *,
    model_name: str,
    notes: list[str] | None = None,
) -> CompetitorDeepAnalysisBundle:
    """Build job-level frontend payload from per-card analyses."""

    return CompetitorDeepAnalysisBundle(
        schema_version="1.0",
        cards=list(cards),
        insufficient_data=bool(cards) and all(c.insufficient_data for c in cards),
        model_name=model_name.strip() or "claude-opus-4-7",
        notes=list(notes or [])[:20],
    )


def _review_texts_for_prompt(reviews: list[CompetitorReview]) -> list[str]:
    texts: list[str] = []
    for review in reviews[:MAX_REVIEW_TEXTS_IN_PROMPT]:
        parts: list[str] = [f"rating={review.rating}"]
        body = (review.text or "").strip()
        if body:
            parts.append(body[:1500])
        if review.pros:
            parts.append(f"pros: {review.pros[:500]}")
        if review.cons:
            parts.append(f"cons: {review.cons[:500]}")
        if len(parts) > 1:
            texts.append(" | ".join(parts))
    return texts


def _kopecks_to_rub(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / 100:.2f}"


def parse_competitor_product_link(url: str) -> CompetitorProductLink:
    """Strictly parse a WB/Ozon product URL into marketplace + article.

    Raises ValueError on unsupported hosts, schemes, or missing article id.
    """

    raw = url.strip()
    if not raw:
        raise ValueError("Link must not be empty.")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("Link must use http or https scheme.")

    host = (parsed.hostname or "").casefold()
    if not host:
        raise ValueError("Link must include a hostname.")

    path = parsed.path or ""

    if host in _WB_HOSTS or host.endswith(".wildberries.ru"):
        match = _WB_CATALOG_PATH.search(path)
        if match is None:
            # Fallback: trailing numeric segment (share / detail links).
            digits = _trailing_digits(path)
            if digits is None:
                raise ValueError(
                    "Wildberries link must contain /catalog/<nmId> product path."
                )
            article = digits
        else:
            article = match.group(1)
        return CompetitorProductLink(
            url=raw,
            marketplace=CompetitorMarketplace.WILDBERRIES,
            article=article,
        )

    if host in _OZON_HOSTS or host.endswith(".ozon.ru"):
        match = _OZON_PRODUCT_PATH.search(path)
        if match is None:
            digits = _trailing_digits(path)
            if digits is None or len(digits) < 6:
                raise ValueError(
                    "Ozon link must contain /product/...<sku> product path."
                )
            article = digits
        else:
            article = match.group(1)
        return CompetitorProductLink(
            url=raw,
            marketplace=CompetitorMarketplace.OZON,
            article=article,
        )

    raise ValueError(
        "Only wildberries.ru / wb.ru and ozon.ru product links are supported."
    )


def _trailing_digits(path: str) -> str | None:
    for part in reversed(path.rstrip("/").split("/")):
        if part.isdigit() and len(part) >= 5:
            return part
        # Ozon slugs often end with -1234567890
        slug_digits = re.search(r"(\d{6,})$", part)
        if slug_digits:
            return slug_digits.group(1)
    return None


def split_reviews_by_rating(
    reviews: list[CompetitorReview],
) -> tuple[list[CompetitorReview], list[CompetitorReview]]:
    """Split reviews into 1–3★ (low) and 4–5★ (high) buckets."""

    low: list[CompetitorReview] = []
    high: list[CompetitorReview] = []
    for review in reviews:
        if review.rating <= 3:
            low.append(review)
        else:
            high.append(review)
    return low, high


def dump_competitor_audit_result(result: CompetitorAuditResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def redis_competitor_audit_key(job_id: UUID, stage: str = "raw") -> str:
    """Redis key for temporary raw parse log (TTL 1 hour)."""

    safe_stage = re.sub(r"[^a-z0-9_\-]", "", stage.casefold()) or "raw"
    return f"analytics:competitor_audit:{job_id}:{safe_stage}"


def truncate_raw_fragment(payload: Any, *, max_chars: int = 40_000) -> Any:
    """Keep raw marketplace fragments cacheable without blowing Redis memory."""

    if isinstance(payload, dict):
        encoded = str(payload)
        if len(encoded) <= max_chars:
            return payload
        return {"_truncated": True, "preview": encoded[:max_chars]}
    if isinstance(payload, list):
        encoded = str(payload)
        if len(encoded) <= max_chars:
            return payload
        return {"_truncated": True, "preview": encoded[:max_chars]}
    text = str(payload)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
