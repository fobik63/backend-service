"""Automated A/B Testing Logic for main marketplace card creatives.

Pipeline:
1. Claude (or deterministic fallback) generates exactly 3 main-card hypotheses
   with distinct creative strategies.
2. Variants are published into the marketplace advertising cabinet.
3. CTR is polled while the experiment runs (default: 7 days).
4. After the window closes, the highest-CTR variant is kept; losers are deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AbExperimentStatus(StrEnum):
    """Lifecycle of an automated A/B experiment."""

    QUEUED = "queued"
    GENERATING = "generating"
    PUBLISHING = "publishing"
    MEASURING = "measuring"
    RESOLVING = "resolving"
    COMPLETED = "completed"
    FAILED = "failed"


class AbVariantStatus(StrEnum):
    """Lifecycle of one creative hypothesis inside an experiment."""

    PENDING = "pending"
    GENERATED = "generated"
    PUBLISHED = "published"
    MEASURING = "measuring"
    WINNER = "winner"
    LOSER = "loser"
    DELETED = "deleted"
    FAILED = "failed"


class AbCreativeStrategy(StrEnum):
    """Canonical strategies for the three main-card variants."""

    PAIN_HOOK = "pain_hook"
    SOCIAL_PROOF = "social_proof"
    OFFER_URGENCY = "offer_urgency"


# Fixed set used by Automated A/B Testing (plan §54).
CANONICAL_STRATEGIES: tuple[AbCreativeStrategy, ...] = (
    AbCreativeStrategy.PAIN_HOOK,
    AbCreativeStrategy.SOCIAL_PROOF,
    AbCreativeStrategy.OFFER_URGENCY,
)

_STRATEGY_LABELS_RU: dict[AbCreativeStrategy, str] = {
    AbCreativeStrategy.PAIN_HOOK: "боль / pain-hook на первом экране",
    AbCreativeStrategy.SOCIAL_PROOF: "социальное доказательство",
    AbCreativeStrategy.OFFER_URGENCY: "оффер и срочность",
}

_STRATEGY_BRIEF_HINTS: dict[AbCreativeStrategy, str] = {
    AbCreativeStrategy.PAIN_HOOK: (
        "Крупный pain-hook на главном слайде: боль покупателя → мгновенное решение. "
        "Минимум текста, максимальный контраст."
    ),
    AbCreativeStrategy.SOCIAL_PROOF: (
        "Соцдоказательство: рейтинг, «хит продаж», число отзывов, до/после. "
        "Доверие важнее скидки."
    ),
    AbCreativeStrategy.OFFER_URGENCY: (
        "Жёсткий оффер: скидка / комплект / дедлайн. "
        "Ценовой бейдж и CTA доминируют на первом экране."
    ),
}


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for A/B Testing payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class AbTestConfig(StrictDomainModel):
    """Tunable thresholds for automated A/B experiments."""

    duration_days: int = Field(default=7, ge=1, le=90)
    variant_count: int = Field(default=3, ge=3, le=3)
    min_impressions_for_decision: int = Field(default=100, ge=0, le=10_000_000)
    min_ctr_gap_pct: float = Field(
        default=0.05,
        ge=0.0,
        le=100.0,
        description="Absolute CTR gap (percentage points) to break near-ties.",
    )
    auto_delete_losers: bool = True
    auto_promote_winner: bool = True

    @model_validator(mode="after")
    def _fixed_variant_count(self) -> AbTestConfig:
        if self.variant_count != len(CANONICAL_STRATEGIES):
            raise ValueError(
                f"variant_count must equal {len(CANONICAL_STRATEGIES)} "
                "(exactly three creative strategies)."
            )
        return self


class AbProductBrief(StrictDomainModel):
    """Seller product context used to generate three card hypotheses."""

    sku: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    category: str | None = Field(default=None, max_length=128)
    key_benefits: list[str] = Field(default_factory=list, max_length=12)
    pain_points: list[str] = Field(default_factory=list, max_length=12)
    current_main_image_url: str | None = Field(default=None, max_length=2048)
    current_offer: str | None = Field(default=None, max_length=300)
    brand_voice: str | None = Field(default=None, max_length=200)
    nm_id: str | None = Field(
        default=None,
        max_length=64,
        description="Marketplace product id (WB nmId / Ozon product_id).",
    )
    campaign_id: str | None = Field(
        default=None,
        max_length=64,
        description="Existing ads campaign to attach creatives to.",
    )

    @field_validator("marketplace", "niche_key", "sku", mode="before")
    @classmethod
    def _strip_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("marketplace", mode="after")
    @classmethod
    def _normalize_marketplace(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("key_benefits", "pain_points", mode="before")
    @classmethod
    def _coerce_string_lists(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, list):
            cleaned: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    cleaned.append(item.strip()[:200])
            return cleaned
        return value


class AbVariantHypothesis(StrictDomainModel):
    """One AI-generated main-card creative hypothesis."""

    strategy: AbCreativeStrategy
    title: str = Field(min_length=1, max_length=200)
    main_image_brief: str = Field(min_length=1, max_length=800)
    offer_hook: str = Field(min_length=1, max_length=300)
    headline: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=500)
    prompt_for_generator: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class AbVariantMetrics(StrictDomainModel):
    """CTR snapshot from the advertising cabinet."""

    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    ctr_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    spend: float | None = Field(default=None, ge=0.0)
    currency: str | None = Field(default=None, max_length=8)
    sampled_at: datetime | None = None

    @model_validator(mode="after")
    def _clicks_lte_impressions(self) -> AbVariantMetrics:
        if self.impressions > 0 and self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions.")
        return self


class AbEnqueueRequest(StrictDomainModel):
    """API/domain request to start an automated A/B experiment."""

    product: AbProductBrief
    config: AbTestConfig | None = None
    ads_credentials_platform: str | None = Field(
        default=None,
        max_length=32,
        description="Override platform key for stored seller/ads credentials.",
    )

    @model_validator(mode="after")
    def _default_platform(self) -> AbEnqueueRequest:
        if not self.ads_credentials_platform:
            object.__setattr__(
                self,
                "ads_credentials_platform",
                self.product.marketplace,
            )
        return self


class AbResolutionResult(StrictDomainModel):
    """Final keep-winner / delete-losers outcome."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    winner_variant_id: UUID | None = None
    winner_strategy: AbCreativeStrategy | None = None
    winner_ctr_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    loser_variant_ids: list[UUID] = Field(default_factory=list)
    deleted_variant_ids: list[UUID] = Field(default_factory=list)
    kept_ads_creative_id: str | None = Field(default=None, max_length=128)
    decision_notes: list[str] = Field(default_factory=list, max_length=40)
    insufficient_traffic: bool = False


@dataclass(frozen=True, slots=True)
class AbVariantView:
    """Projection of one experiment variant."""

    id: UUID
    experiment_id: UUID
    position: int
    strategy: AbCreativeStrategy
    status: AbVariantStatus
    title: str | None
    main_image_brief: str | None
    offer_hook: str | None
    headline: str | None
    rationale: str | None
    prompt_for_generator: str | None
    confidence: float | None
    ads_creative_id: str | None
    ads_campaign_id: str | None
    marketplace_media_id: str | None
    impressions: int
    clicks: int
    ctr_pct: float
    spend: float | None
    metrics_sampled_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AbExperimentView:
    """Projection of an automated A/B experiment aggregate."""

    id: UUID
    user_id: UUID
    status: AbExperimentStatus
    celery_task_id: str | None
    marketplace: str
    niche_key: str
    sku: str
    nm_id: str | None
    campaign_id: str | None
    model_name: str
    product_payload: dict[str, Any]
    config: dict[str, Any]
    hypotheses_payload: list[dict[str, Any]] | None
    resolution_result: dict[str, Any] | None
    winner_variant_id: UUID | None
    measurement_started_at: datetime | None
    measurement_ends_at: datetime | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    variants: tuple[AbVariantView, ...] = ()


AB_HYPOTHESES_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["variants", "reasoning_trace"],
    "properties": {
        "variants": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "strategy",
                    "title",
                    "main_image_brief",
                    "offer_hook",
                    "headline",
                    "rationale",
                    "prompt_for_generator",
                    "confidence",
                ],
                "properties": {
                    "strategy": {
                        "type": "string",
                        "enum": [s.value for s in AbCreativeStrategy],
                    },
                    "title": {"type": "string"},
                    "main_image_brief": {"type": "string"},
                    "offer_hook": {"type": "string"},
                    "headline": {"type": "string"},
                    "rationale": {"type": "string"},
                    "prompt_for_generator": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "reasoning_trace": {"type": "string"},
    },
}


def strategy_label_ru(strategy: AbCreativeStrategy) -> str:
    """Human-readable Russian label for a creative strategy."""

    return _STRATEGY_LABELS_RU[strategy]


def compute_ctr_pct(*, impressions: int, clicks: int) -> float:
    """CTR as a percentage with two decimal places."""

    if impressions <= 0:
        return 0.0
    if clicks < 0:
        raise ValueError("clicks cannot be negative.")
    if clicks > impressions:
        raise ValueError("clicks cannot exceed impressions.")
    return round((clicks / impressions) * 100.0, 4)


def measurement_window_end(
    *,
    started_at: datetime,
    duration_days: int,
) -> datetime:
    """UTC end of the A/B measurement window."""

    if duration_days <= 0:
        raise ValueError("duration_days must be positive.")
    start = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    return start.astimezone(UTC) + timedelta(days=duration_days)


def is_measurement_complete(
    *,
    measurement_ends_at: datetime,
    now: datetime | None = None,
) -> bool:
    """True when the configured A/B window has elapsed."""

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    end = measurement_ends_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return clock.astimezone(UTC) >= end.astimezone(UTC)


def build_deterministic_hypotheses(
    product: AbProductBrief,
) -> tuple[AbVariantHypothesis, ...]:
    """Fallback hypotheses when Claude is unavailable (still exactly 3)."""

    pain = product.pain_points[0] if product.pain_points else "главная боль покупателя"
    benefit = (
        product.key_benefits[0] if product.key_benefits else "ключевое преимущество"
    )
    offer = product.current_offer or "выгодное предложение сегодня"

    templates: dict[AbCreativeStrategy, dict[str, str]] = {
        AbCreativeStrategy.PAIN_HOOK: {
            "title": f"{product.title}: решение боли «{pain}»",
            "main_image_brief": (
                f"Главный слайд: крупный заголовок про «{pain}», продукт в фокусе, "
                f"контрастный акцент на решении «{benefit}»."
            ),
            "offer_hook": f"Закрываем боль: {pain} → {benefit}",
            "headline": f"Устали от «{pain}»?",
            "rationale": (
                f"Стратегия pain-hook бьёт в слепую выдачу: боль «{pain}» "
                "считывается за 1–2 секунды."
            ),
            "prompt_for_generator": (
                f"Marketplace main card for {product.title}. Pain-hook first slide: "
                f"buyer pain '{pain}', solution '{benefit}'. High contrast, "
                f"minimal text, {_STRATEGY_BRIEF_HINTS[AbCreativeStrategy.PAIN_HOOK]}"
            ),
        },
        AbCreativeStrategy.SOCIAL_PROOF: {
            "title": f"{product.title}: хит с доказательством",
            "main_image_brief": (
                "Главный слайд: рейтинг ★★★★★, бейдж «хит продаж», "
                f"выгода «{benefit}», спокойный lifestyle-фон."
            ),
            "offer_hook": f"Выбор покупателей: {benefit}",
            "headline": "Нам доверяют тысячи покупателей",
            "rationale": (
                "Социальное доказательство снижает риск клика и поднимает CTR "
                "у скептичной аудитории."
            ),
            "prompt_for_generator": (
                f"Marketplace main card for {product.title}. Social proof: stars, "
                f"bestseller badge, benefit '{benefit}'. "
                f"{_STRATEGY_BRIEF_HINTS[AbCreativeStrategy.SOCIAL_PROOF]}"
            ),
        },
        AbCreativeStrategy.OFFER_URGENCY: {
            "title": f"{product.title}: {offer}",
            "main_image_brief": (
                f"Главный слайд: крупный ценовой/оффер бейдж «{offer}», "
                "таймер/срочность, продукт крупно справа."
            ),
            "offer_hook": offer,
            "headline": f"Только сейчас: {offer}",
            "rationale": (
                "Оффер и срочность усиливают импульсный клик в рекламной выдаче."
            ),
            "prompt_for_generator": (
                f"Marketplace main card for {product.title}. Offer urgency: "
                f"'{offer}', bold price badge, scarce CTA. "
                f"{_STRATEGY_BRIEF_HINTS[AbCreativeStrategy.OFFER_URGENCY]}"
            ),
        },
    }

    variants: list[AbVariantHypothesis] = []
    for strategy in CANONICAL_STRATEGIES:
        tmpl = templates[strategy]
        variants.append(
            AbVariantHypothesis.model_validate(
                {
                    "strategy": strategy,
                    "title": tmpl["title"][:200],
                    "main_image_brief": tmpl["main_image_brief"][:800],
                    "offer_hook": tmpl["offer_hook"][:300],
                    "headline": tmpl["headline"][:200],
                    "rationale": tmpl["rationale"][:500],
                    "prompt_for_generator": tmpl["prompt_for_generator"][:1200],
                    "confidence": 0.65,
                }
            )
        )
    return tuple(variants)


def normalize_hypotheses(
    raw: list[AbVariantHypothesis] | list[dict[str, Any]],
) -> tuple[AbVariantHypothesis, ...]:
    """Ensure exactly one hypothesis per canonical strategy (order preserved)."""

    parsed: list[AbVariantHypothesis] = []
    for item in raw:
        if isinstance(item, AbVariantHypothesis):
            parsed.append(item)
        else:
            parsed.append(AbVariantHypothesis.model_validate(item))

    by_strategy: dict[AbCreativeStrategy, AbVariantHypothesis] = {}
    for hyp in parsed:
        if hyp.strategy not in by_strategy:
            by_strategy[hyp.strategy] = hyp

    missing = [s for s in CANONICAL_STRATEGIES if s not in by_strategy]
    if missing:
        raise ValueError(
            "A/B hypotheses must cover all strategies; missing: "
            + ", ".join(s.value for s in missing)
        )

    return tuple(by_strategy[s] for s in CANONICAL_STRATEGIES)


def select_winner_variant(
    variants: tuple[AbVariantView, ...] | list[AbVariantView],
    *,
    config: AbTestConfig,
) -> tuple[AbVariantView | None, list[str]]:
    """Pick the highest-CTR published/measuring variant.

    Tie-break: higher clicks → lower position (canonical strategy order).
    Returns (winner_or_none, decision_notes).
    """

    notes: list[str] = []
    eligible = [
        v
        for v in variants
        if v.status
        in (
            AbVariantStatus.PUBLISHED,
            AbVariantStatus.MEASURING,
            AbVariantStatus.GENERATED,
        )
        or (
            v.impressions > 0
            and v.status
            not in (AbVariantStatus.FAILED, AbVariantStatus.DELETED, AbVariantStatus.LOSER)
        )
    ]
    # Prefer variants that actually entered measurement.
    measuring = [
        v
        for v in variants
        if v.status
        in (
            AbVariantStatus.MEASURING,
            AbVariantStatus.PUBLISHED,
            AbVariantStatus.WINNER,
        )
        or v.ads_creative_id is not None
    ]
    pool = measuring or eligible
    if not pool:
        notes.append("Нет вариантов с опубликованными креативами для выбора победителя.")
        return None, notes

    total_impressions = sum(v.impressions for v in pool)
    if total_impressions < config.min_impressions_for_decision:
        notes.append(
            f"Недостаточно трафика для уверенного решения "
            f"({total_impressions} < {config.min_impressions_for_decision} показов)."
        )

    ranked = sorted(
        pool,
        key=lambda v: (-v.ctr_pct, -v.clicks, -v.impressions, v.position),
    )
    winner = ranked[0]
    if len(ranked) > 1:
        runner = ranked[1]
        gap = winner.ctr_pct - runner.ctr_pct
        notes.append(
            f"Победитель: {winner.strategy.value} (CTR {winner.ctr_pct:.2f}%) "
            f"против {runner.strategy.value} (CTR {runner.ctr_pct:.2f}%), "
            f"разрыв {gap:.2f} п.п."
        )
        if gap < config.min_ctr_gap_pct and winner.clicks == runner.clicks:
            notes.append(
                "Разрыв CTR ниже порога — победитель выбран по тай-брейку "
                "(клики → порядок стратегии)."
            )
    else:
        notes.append(
            f"Единственный измеримый вариант: {winner.strategy.value} "
            f"(CTR {winner.ctr_pct:.2f}%)."
        )
    return winner, notes


def build_resolution_result(
    *,
    variants: tuple[AbVariantView, ...] | list[AbVariantView],
    config: AbTestConfig,
    deleted_variant_ids: list[UUID] | None = None,
    kept_ads_creative_id: str | None = None,
) -> AbResolutionResult:
    """Compose the final keep/delete resolution payload."""

    winner, notes = select_winner_variant(variants, config=config)
    total_impressions = sum(v.impressions for v in variants)
    insufficient = total_impressions < config.min_impressions_for_decision

    if winner is None:
        return AbResolutionResult(
            decision_notes=notes or ["Победитель не определён."],
            insufficient_traffic=insufficient,
        )

    loser_ids = [v.id for v in variants if v.id != winner.id]
    return AbResolutionResult(
        winner_variant_id=winner.id,
        winner_strategy=winner.strategy,
        winner_ctr_pct=winner.ctr_pct,
        loser_variant_ids=loser_ids,
        deleted_variant_ids=list(deleted_variant_ids or []),
        kept_ads_creative_id=kept_ads_creative_id or winner.ads_creative_id,
        decision_notes=notes,
        insufficient_traffic=insufficient,
    )


def ab_system_prompt() -> str:
    """System prompt for Claude A/B hypothesis generation."""

    strategies = ", ".join(s.value for s in CANONICAL_STRATEGIES)
    return (
        "You are Automated A/B Testing — a marketplace creative strategist for "
        "Wildberries and Ozon advertising cabinets. "
        f"Generate EXACTLY 3 distinct main-card hypotheses, one per strategy: {strategies}. "
        "Each variant must differ clearly in visual hook and offer framing. "
        "Write titles, headlines, image briefs, and rationales in Russian. "
        "prompt_for_generator may be English for image models. "
        "Return strict JSON matching the provided schema."
    )


def build_ab_hypotheses_prompt(*, product: AbProductBrief) -> str:
    """User prompt with product brief for Claude JSON Mode."""

    benefits = ", ".join(product.key_benefits) or "—"
    pains = ", ".join(product.pain_points) or "—"
    lines = [
        "Сгенерируй 3 варианта главной карточки для A/B теста в рекламном кабинете.",
        f"Маркетплейс: {product.marketplace}",
        f"SKU: {product.sku}",
        f"Ниша: {product.niche_key}",
        f"Название: {product.title}",
        f"Категория: {product.category or '—'}",
        f"Выгоды: {benefits}",
        f"Боли: {pains}",
        f"Текущий оффер: {product.current_offer or '—'}",
        f"Голос бренда: {product.brand_voice or '—'}",
        "",
        "Стратегии (обязательно по одной на вариант):",
    ]
    for strategy in CANONICAL_STRATEGIES:
        lines.append(
            f"- {strategy.value}: {_STRATEGY_BRIEF_HINTS[strategy]}"
        )
    lines.append(
        "\nКаждый вариант: title, headline, main_image_brief, offer_hook, "
        "rationale, prompt_for_generator, confidence."
    )
    return "\n".join(lines)


def redis_ab_stage_key(experiment_id: UUID, stage: str) -> str:
    """Redis key for intermediate A/B stage payloads."""

    return f"ab_test:{experiment_id}:{stage}"


def dump_hypotheses(
    hypotheses: tuple[AbVariantHypothesis, ...] | list[AbVariantHypothesis],
) -> list[dict[str, Any]]:
    """Serialize hypotheses for JSONB persistence."""

    return [h.model_dump(mode="json") for h in hypotheses]


def dump_resolution(result: AbResolutionResult) -> dict[str, Any]:
    """Serialize resolution result for JSONB persistence."""

    return result.model_dump(mode="json")
