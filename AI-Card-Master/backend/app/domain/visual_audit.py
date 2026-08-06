"""Intelligent visual audit for Claude 4.7: survivor-bias filter + Rising Stars.

Pipeline:
1. Take top-N niche cards (default 50).
2. Strictly filter by review count + review/sales velocity from the stock parser.
3. Mark Brand Dominant monsters and EXCLUDE their visuals from trigger math.
4. Keep Rising Stars (moderate reviews + anomalous sales growth).
5. Dissect Rising Star visuals via Claude Vision → strict generator JSON config.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VisualAuditJobStatus(StrEnum):
    """Lifecycle of an async niche visual-audit job."""

    QUEUED = "queued"
    FILTERING = "filtering"
    VISION_RUNNING = "vision_running"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"


class CardCohortLabel(StrEnum):
    """Cohort assigned before any Claude Vision spend."""

    BRAND_DOMINANT = "brand_dominant"
    RISING_STAR = "rising_star"
    NEUTRAL = "neutral"
    INSUFFICIENT_DATA = "insufficient_data"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for visual-audit payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class VisualAuditFilterConfig(StrictDomainModel):
    """Tunable thresholds for Brand Dominant / Rising Star selection."""

    top_n: int = Field(default=50, ge=1, le=200)
    brand_dominant_soft_reviews: int = Field(default=5000, ge=1000, le=50_000)
    brand_dominant_hard_reviews: int = Field(default=7000, ge=1000, le=50_000)
    rising_min_reviews: int = Field(default=50, ge=1, le=10_000)
    rising_max_reviews: int = Field(default=1500, ge=10, le=50_000)
    min_sales_growth_ratio: float = Field(default=0.30, ge=0.0, le=10.0)
    min_review_velocity_per_day: float = Field(default=3.0, ge=0.0, le=10_000.0)
    max_rising_stars_for_vision: int = Field(default=12, ge=1, le=50)

    @model_validator(mode="after")
    def _validate_bands(self) -> VisualAuditFilterConfig:
        if self.brand_dominant_soft_reviews > self.brand_dominant_hard_reviews:
            raise ValueError(
                "brand_dominant_soft_reviews must be <= brand_dominant_hard_reviews."
            )
        if self.rising_min_reviews > self.rising_max_reviews:
            raise ValueError("rising_min_reviews must be <= rising_max_reviews.")
        if self.rising_max_reviews >= self.brand_dominant_soft_reviews:
            raise ValueError(
                "rising_max_reviews must stay below brand_dominant_soft_reviews "
                "to avoid cohort overlap."
            )
        return self


class NicheCardSignal(StrictDomainModel):
    """One marketplace card with review + stock-parser dynamics."""

    sku: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    rank: int | None = Field(default=None, ge=1, le=10_000)
    review_count: int = Field(ge=0, le=10_000_000)
    review_count_delta: int = Field(default=0, ge=0, le=10_000_000)
    observation_days: int = Field(default=7, ge=1, le=90)
    avg_daily_sales_baseline: float | None = Field(default=None, ge=0.0)
    avg_daily_sales_recent: float | None = Field(default=None, ge=0.0)
    stock_quantity_start: int | None = Field(default=None, ge=0)
    stock_quantity_end: int | None = Field(default=None, ge=0)
    image_object_keys: list[str] = Field(default_factory=list, max_length=10)
    product_category: str | None = Field(default=None, max_length=128)

    @field_validator("image_object_keys", mode="before")
    @classmethod
    def _coerce_keys(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("image_object_keys must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("image_object_keys items must be strings.")
            key = item.strip()
            if key:
                cleaned.append(key)
        return cleaned


class ClassifiedNicheCard(StrictDomainModel):
    """Card after survivor-bias / Rising Star classification."""

    sku: str = Field(min_length=1, max_length=64)
    title: str | None = None
    rank: int | None = None
    review_count: int = Field(ge=0)
    review_velocity_per_day: float = Field(ge=0.0)
    sales_growth_ratio: float | None = None
    estimated_units_sold: int | None = Field(default=None, ge=0)
    cohort: CardCohortLabel
    exclude_from_trigger_math: bool
    rising_score: float = Field(ge=0.0, le=100.0)
    reason: str = Field(min_length=1, max_length=500)
    image_object_keys: list[str] = Field(default_factory=list, max_length=10)
    product_category: str | None = None


class NicheFilterReport(StrictDomainModel):
    """Deterministic pre-Vision filter result for a niche top-N scan."""

    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    scanned_count: int = Field(ge=0)
    config: VisualAuditFilterConfig
    brand_dominant: list[ClassifiedNicheCard] = Field(default_factory=list)
    rising_stars: list[ClassifiedNicheCard] = Field(default_factory=list)
    neutrals: list[ClassifiedNicheCard] = Field(default_factory=list)
    insufficient: list[ClassifiedNicheCard] = Field(default_factory=list)
    vision_queue: list[ClassifiedNicheCard] = Field(default_factory=list)
    filter_notes: list[str] = Field(default_factory=list, max_length=40)


class RisingStarPainHook(StrictDomainModel):
    """Pain closed on the first slide of a Rising Star card."""

    pain: str = Field(min_length=1, max_length=300)
    visual_device: str = Field(min_length=1, max_length=300)
    placement: str = Field(min_length=1, max_length=128)


class RisingStarVisionDissection(StrictDomainModel):
    """Claude Vision deep-dive for one Rising Star (money-validated cohort)."""

    sku: str = Field(min_length=1, max_length=64)
    first_slide_pain_hooks: list[RisingStarPainHook] = Field(min_length=1, max_length=8)
    infographic_structure: str = Field(min_length=1, max_length=800)
    contrast_accents: list[str] = Field(min_length=1, max_length=12)
    offer_pattern: str = Field(min_length=1, max_length=500)
    blind_search_winning_moves: list[str] = Field(min_length=1, max_length=12)
    money_validated_triggers: list[str] = Field(min_length=1, max_length=12)
    avoid_copying: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_trace: str = Field(min_length=1, max_length=4000)


class MoneyValidatedTrigger(StrictDomainModel):
    """One conversion trigger proven by Rising Star sales dynamics."""

    trigger_id: str = Field(min_length=1, max_length=64)
    source_sku: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    pain_on_first_slide: str = Field(min_length=1, max_length=300)
    infographic_structure: str = Field(min_length=1, max_length=800)
    contrast_accents: list[str] = Field(default_factory=list, max_length=12)
    offer_pattern: str = Field(min_length=1, max_length=500)
    sales_growth_ratio: float | None = None
    review_velocity_per_day: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rising_score: float = Field(ge=0.0, le=100.0)


class GeneratorDirectives(StrictDomainModel):
    """Directives consumed by the image/text generator."""

    first_slide_pain_hooks: list[str] = Field(default_factory=list, max_length=20)
    infographic_layouts: list[str] = Field(default_factory=list, max_length=20)
    contrast_palette_hints: list[str] = Field(default_factory=list, max_length=24)
    offer_patterns: list[str] = Field(default_factory=list, max_length=20)
    blind_search_winning_moves: list[str] = Field(default_factory=list, max_length=20)
    forbidden_brand_mimicry: list[str] = Field(default_factory=list, max_length=20)


class GeneratorTriggerConfig(StrictDomainModel):
    """Strict JSON config for the generator — brand-giant noise stripped out."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    survivor_bias_excluded: bool = True
    brand_dominant_excluded_skus: list[str] = Field(default_factory=list, max_length=200)
    rising_star_skus: list[str] = Field(default_factory=list, max_length=50)
    money_validated_triggers: list[MoneyValidatedTrigger] = Field(
        default_factory=list, max_length=40
    )
    generator_directives: GeneratorDirectives
    model_name: str = Field(min_length=1, max_length=128)
    confidence_score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list, max_length=40)


class VisualAuditEnqueueRequest(StrictDomainModel):
    """API/domain request to audit a niche top-N set."""

    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    cards: list[NicheCardSignal] = Field(min_length=1, max_length=200)
    filter_config: VisualAuditFilterConfig | None = None


@dataclass(frozen=True, slots=True)
class VisualAuditJobView:
    """Projection of a persisted visual-audit job."""

    id: UUID
    user_id: UUID
    status: VisualAuditJobStatus
    celery_task_id: str | None
    niche_key: str
    marketplace: str
    cards_payload: tuple[dict[str, Any], ...]
    filter_config: dict[str, Any]
    filter_report: dict[str, Any] | None
    vision_dissections: list[dict[str, Any]] | None
    generator_config: dict[str, Any] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


RISING_STAR_VISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sku",
        "first_slide_pain_hooks",
        "infographic_structure",
        "contrast_accents",
        "offer_pattern",
        "blind_search_winning_moves",
        "money_validated_triggers",
        "avoid_copying",
        "confidence",
        "reasoning_trace",
    ],
    "properties": {
        "sku": {"type": "string"},
        "first_slide_pain_hooks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pain", "visual_device", "placement"],
                "properties": {
                    "pain": {"type": "string"},
                    "visual_device": {"type": "string"},
                    "placement": {"type": "string"},
                },
            },
        },
        "infographic_structure": {"type": "string"},
        "contrast_accents": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "offer_pattern": {"type": "string"},
        "blind_search_winning_moves": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "money_validated_triggers": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "avoid_copying": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "reasoning_trace": {"type": "string"},
    },
}


_RISING_STAR_VISION_SYSTEM_PROMPT = (
    "You are a senior marketplace visual conversion strategist for Wildberries and Ozon. "
    "You analyze ONLY Rising Star cards: moderate review counts with anomalous sales "
    "growth proven by stock-parser data. Brand-dominant giants are already excluded. "
    "Dissect the visual: first-slide pain hooks, infographic structure, contrast accents "
    "that win in blind marketplace search. "
    "Return ONLY valid JSON matching the schema. Do not invent elements not visible. "
    "Never recommend copying mega-brand logo / heritage trust patterns."
)


def rising_star_vision_system_prompt() -> str:
    return _RISING_STAR_VISION_SYSTEM_PROMPT


def build_rising_star_vision_prompt(
    *,
    sku: str,
    title: str | None,
    product_category: str | None,
    sales_growth_ratio: float | None,
    review_velocity_per_day: float,
    review_count: int,
    image_count: int,
) -> str:
    """Prompt for Claude Vision dissection of one Rising Star card."""

    growth = (
        f"{sales_growth_ratio:.0%}"
        if sales_growth_ratio is not None
        else "не рассчитан"
    )
    category = (product_category or "не указана").strip() or "не указана"
    card_title = (title or sku).strip() or sku
    return (
        f"Препарируй визуал Rising Star (тёмная лошадка) SKU={sku}. "
        f"Название: {card_title}. Категория: {category}. "
        f"Отзывов: {review_count}. Velocity отзывов: {review_velocity_per_day:.2f}/день. "
        f"Аномальный прирост продаж (парсер остатков): {growth}. "
        f"Изображений: {image_count}. "
        "Выдели: какие боли закрыты на первом слайде, структуру инфографики, "
        "контрастные акценты для слепой выдачи. "
        "Триггеры должны быть money-validated (рост продаж), без копирования брендовых гигантов. "
        "Сначала рассуждай в reasoning_trace, затем заполни JSON. "
        f"Поле sku в ответе должно быть ровно: {sku}."
    )


def estimate_units_sold_from_stock(card: NicheCardSignal) -> int | None:
    """Estimate units sold from stock-parser start/end snapshots."""

    if card.stock_quantity_start is None or card.stock_quantity_end is None:
        return None
    return max(0, card.stock_quantity_start - card.stock_quantity_end)


def compute_sales_growth_ratio(card: NicheCardSignal) -> float | None:
    """Sales growth vs baseline; falls back to stock-delta proxy when needed."""

    baseline = card.avg_daily_sales_baseline
    recent = card.avg_daily_sales_recent
    if baseline is not None and recent is not None:
        if baseline <= 0:
            return 1.0 if recent > 0 else 0.0
        return (recent - baseline) / baseline

    units = estimate_units_sold_from_stock(card)
    if units is None:
        return None
    daily = units / max(card.observation_days, 1)
    # Without baseline, treat any meaningful stock burn as weak positive signal only.
    if daily <= 0:
        return 0.0
    # Proxy: normalize against a soft floor so young movers still surface.
    proxy_baseline = max(daily * 0.5, 1.0)
    return (daily - proxy_baseline) / proxy_baseline


def compute_review_velocity_per_day(card: NicheCardSignal) -> float:
    """Reviews gained per observation day."""

    return card.review_count_delta / max(card.observation_days, 1)


def _rising_score(
    *,
    sales_growth_ratio: float | None,
    review_velocity: float,
    config: VisualAuditFilterConfig,
) -> float:
    growth = max(sales_growth_ratio or 0.0, 0.0)
    growth_norm = min(growth / max(config.min_sales_growth_ratio, 1e-6), 2.0) / 2.0
    vel_norm = min(
        review_velocity / max(config.min_review_velocity_per_day, 1e-6), 2.0
    ) / 2.0
    return round(100.0 * (0.65 * growth_norm + 0.35 * vel_norm), 2)


def classify_niche_card(
    card: NicheCardSignal,
    config: VisualAuditFilterConfig,
) -> ClassifiedNicheCard:
    """Classify one card; Brand Dominant visuals are hard-excluded from trigger math."""

    velocity = compute_review_velocity_per_day(card)
    growth = compute_sales_growth_ratio(card)
    units = estimate_units_sold_from_stock(card)
    score = _rising_score(
        sales_growth_ratio=growth,
        review_velocity=velocity,
        config=config,
    )

    base_kwargs: dict[str, Any] = {
        "sku": card.sku,
        "title": card.title,
        "rank": card.rank,
        "review_count": card.review_count,
        "review_velocity_per_day": round(velocity, 4),
        "sales_growth_ratio": None if growth is None else round(growth, 4),
        "estimated_units_sold": units,
        "image_object_keys": list(card.image_object_keys),
        "product_category": card.product_category,
    }

    if card.review_count >= config.brand_dominant_soft_reviews:
        band = (
            "hard"
            if card.review_count >= config.brand_dominant_hard_reviews
            else "soft"
        )
        return ClassifiedNicheCard(
            **base_kwargs,
            cohort=CardCohortLabel.BRAND_DOMINANT,
            exclude_from_trigger_math=True,
            rising_score=0.0,
            reason=(
                f"Brand Dominant ({band}): {card.review_count} отзывов ≥ "
                f"{config.brand_dominant_soft_reviews}. Покупки по инерции/бренду — "
                "визуал исключён из расчёта конверсионных триггеров."
            ),
        )

    if card.review_count < config.rising_min_reviews:
        return ClassifiedNicheCard(
            **base_kwargs,
            cohort=CardCohortLabel.INSUFFICIENT_DATA,
            exclude_from_trigger_math=True,
            rising_score=0.0,
            reason=(
                f"Мало отзывов ({card.review_count} < {config.rising_min_reviews}): "
                "недостаточно сигнала для money-validated аудита."
            ),
        )

    in_rising_band = (
        config.rising_min_reviews <= card.review_count <= config.rising_max_reviews
    )
    anomalous_sales = (
        growth is not None and growth >= config.min_sales_growth_ratio
    )
    strong_velocity = velocity >= config.min_review_velocity_per_day

    if in_rising_band and anomalous_sales:
        velocity_note = (
            f"velocity {velocity:.2f}/день подтверждает разгон."
            if strong_velocity
            else (
                f"velocity {velocity:.2f}/день ниже порога "
                f"{config.min_review_velocity_per_day}, но аномалия продаж достаточна."
            )
        )
        return ClassifiedNicheCard(
            **base_kwargs,
            cohort=CardCohortLabel.RISING_STAR,
            exclude_from_trigger_math=False,
            rising_score=score,
            reason=(
                f"Rising Star: отзывы {card.review_count} в окне "
                f"[{config.rising_min_reviews}, {config.rising_max_reviews}], "
                f"прирост продаж {growth:.0%} ≥ {config.min_sales_growth_ratio:.0%}. "
                f"{velocity_note}"
            ),
        )

    if in_rising_band and not anomalous_sales and strong_velocity:
        # Velocity alone is a watch signal, not enough for money-validated triggers.
        return ClassifiedNicheCard(
            **base_kwargs,
            cohort=CardCohortLabel.NEUTRAL,
            exclude_from_trigger_math=True,
            rising_score=round(score * 0.5, 2),
            reason=(
                "Умеренные отзывы и высокая velocity, но нет аномального прироста "
                "продаж по парсеру остатков — в vision-очередь не берём."
            ),
        )

    return ClassifiedNicheCard(
        **base_kwargs,
        cohort=CardCohortLabel.NEUTRAL,
        exclude_from_trigger_math=True,
        rising_score=0.0,
        reason=(
            "Вне Rising Star критериев: нет связки умеренных отзывов + "
            "аномальный прирост продаж."
        ),
    )


def filter_niche_top_cards(
    *,
    niche_key: str,
    marketplace: str,
    cards: list[NicheCardSignal],
    config: VisualAuditFilterConfig | None = None,
) -> NicheFilterReport:
    """Strict pre-scan filter for top niche cards (survivor bias removed)."""

    cfg = config or VisualAuditFilterConfig()
    # Deterministic order: rank asc, then review_count desc, then sku.
    ordered = sorted(
        cards,
        key=lambda c: (
            c.rank if c.rank is not None else 10_000,
            -c.review_count,
            c.sku,
        ),
    )[: cfg.top_n]

    brand_dominant: list[ClassifiedNicheCard] = []
    rising_stars: list[ClassifiedNicheCard] = []
    neutrals: list[ClassifiedNicheCard] = []
    insufficient: list[ClassifiedNicheCard] = []

    for card in ordered:
        classified = classify_niche_card(card, cfg)
        if classified.cohort == CardCohortLabel.BRAND_DOMINANT:
            brand_dominant.append(classified)
        elif classified.cohort == CardCohortLabel.RISING_STAR:
            rising_stars.append(classified)
        elif classified.cohort == CardCohortLabel.INSUFFICIENT_DATA:
            insufficient.append(classified)
        else:
            neutrals.append(classified)

    rising_stars.sort(key=lambda c: (-c.rising_score, c.sku))
    vision_queue = [
        card
        for card in rising_stars
        if card.image_object_keys
    ][: cfg.max_rising_stars_for_vision]

    notes = [
        "Brand Dominant visuals are fully excluded from conversion-trigger math.",
        "Rising Stars require reviews in [50, 1500] (configurable) plus anomalous "
        "sales growth from the stock parser; review velocity ranks the queue.",
    ]
    if not rising_stars:
        notes.append("No Rising Stars found in this niche slice.")
    skipped_no_images = len(rising_stars) - len(
        [c for c in rising_stars if c.image_object_keys]
    )
    if skipped_no_images > 0:
        notes.append(
            f"{skipped_no_images} Rising Star(s) skipped for Vision: no image_object_keys."
        )

    return NicheFilterReport(
        niche_key=niche_key.strip(),
        marketplace=marketplace.strip().lower(),
        scanned_count=len(ordered),
        config=cfg,
        brand_dominant=brand_dominant,
        rising_stars=rising_stars,
        neutrals=neutrals,
        insufficient=insufficient,
        vision_queue=vision_queue,
        filter_notes=notes,
    )


def _dedupe_preserve(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = " ".join(item.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= limit:
            break
    return out


def build_generator_trigger_config(
    *,
    filter_report: NicheFilterReport,
    dissections: list[RisingStarVisionDissection],
    model_name: str,
) -> GeneratorTriggerConfig:
    """Aggregate Rising Star vision into a brand-noise-free generator JSON config."""

    rising_by_sku = {card.sku: card for card in filter_report.rising_stars}
    triggers: list[MoneyValidatedTrigger] = []
    pain_hooks: list[str] = []
    layouts: list[str] = []
    accents: list[str] = []
    offers: list[str] = []
    winning_moves: list[str] = []
    forbidden: list[str] = [
        "Не копировать композицию и логотипные якоря Brand Dominant карточек",
        "Не опираться на узнаваемость бренда / доверие к старому продавцу",
        "Использовать только паттерны Rising Stars с аномальным приростом продаж",
    ]

    for dissection in dissections:
        source = rising_by_sku.get(dissection.sku)
        if source is None:
            # Safety: never accept Brand Dominant / unknown SKUs into trigger math.
            continue
        if source.exclude_from_trigger_math:
            continue

        for index, trigger_text in enumerate(dissection.money_validated_triggers, start=1):
            hook = (
                dissection.first_slide_pain_hooks[0].pain
                if dissection.first_slide_pain_hooks
                else "боль покупателя"
            )
            triggers.append(
                MoneyValidatedTrigger(
                    trigger_id=f"{dissection.sku}-t{index}",
                    source_sku=dissection.sku,
                    category="rising_star_visual",
                    description=trigger_text,
                    pain_on_first_slide=hook,
                    infographic_structure=dissection.infographic_structure,
                    contrast_accents=list(dissection.contrast_accents),
                    offer_pattern=dissection.offer_pattern,
                    sales_growth_ratio=source.sales_growth_ratio,
                    review_velocity_per_day=source.review_velocity_per_day,
                    confidence=dissection.confidence,
                    rising_score=source.rising_score,
                )
            )

        pain_hooks.extend(
            f"{hook.pain} → {hook.visual_device} ({hook.placement})"
            for hook in dissection.first_slide_pain_hooks
        )
        layouts.append(dissection.infographic_structure)
        accents.extend(dissection.contrast_accents)
        offers.append(dissection.offer_pattern)
        winning_moves.extend(dissection.blind_search_winning_moves)
        forbidden.extend(dissection.avoid_copying)

    # Rank triggers by money signals, then confidence.
    triggers.sort(
        key=lambda t: (
            -(t.sales_growth_ratio or 0.0),
            -t.rising_score,
            -t.confidence,
            t.trigger_id,
        )
    )
    triggers = triggers[:40]

    confidences = [t.confidence for t in triggers]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    if filter_report.rising_stars and not triggers:
        notes = [
            "Rising Stars найдены, но Vision-диссекции не дали валидных триггеров "
            "или отсутствовали изображения."
        ]
        confidence_score = 0.0
    elif not filter_report.rising_stars:
        notes = list(filter_report.filter_notes)
        notes.append("Пустой generator config: в нише нет Rising Stars.")
        confidence_score = 0.0
    else:
        notes = list(filter_report.filter_notes)
        notes.append(
            f"В конфиг вошло {len(triggers)} money-validated триггеров "
            f"из {len(dissections)} Rising Star диссекций."
        )
        confidence_score = round(min(1.0, max(0.0, avg_conf)), 4)

    return GeneratorTriggerConfig(
        schema_version="1.0",
        niche_key=filter_report.niche_key,
        marketplace=filter_report.marketplace,
        survivor_bias_excluded=True,
        brand_dominant_excluded_skus=[
            card.sku for card in filter_report.brand_dominant
        ],
        rising_star_skus=[card.sku for card in filter_report.rising_stars],
        money_validated_triggers=triggers,
        generator_directives=GeneratorDirectives(
            first_slide_pain_hooks=_dedupe_preserve(pain_hooks, limit=20),
            infographic_layouts=_dedupe_preserve(layouts, limit=20),
            contrast_palette_hints=_dedupe_preserve(accents, limit=24),
            offer_patterns=_dedupe_preserve(offers, limit=20),
            blind_search_winning_moves=_dedupe_preserve(winning_moves, limit=20),
            forbidden_brand_mimicry=_dedupe_preserve(forbidden, limit=20),
        ),
        model_name=model_name,
        confidence_score=confidence_score,
        notes=notes[:40],
    )


def redis_visual_audit_key(job_id: UUID, stage: str) -> str:
    """Redis key for intermediate visual-audit payloads."""

    return f"claude:visual_audit:{job_id}:{stage}"


def dump_filter_report(report: NicheFilterReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


def dump_generator_config(config: GeneratorTriggerConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def generator_config_json(config: GeneratorTriggerConfig) -> str:
    """Canonical JSON string for generator hand-off."""

    return json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)


def entropy_safe_divide(numerator: float, denominator: float) -> float:
    """Small helper used by tests / scoring edge cases."""

    if denominator == 0 or math.isclose(denominator, 0.0):
        return 0.0
    return numerator / denominator
