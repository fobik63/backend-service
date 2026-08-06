"""Strategic 'Killer' Recommendations Engine (AI Strategy).

Pipeline:
1. Compare the seller's card against the niche leader across visual/copy dimensions.
2. Emit deterministic feature deltas ordered from background → title.
3. Attach CTR-backed rationale per step:
   «Конкурент использует это и имеет на 15% выше CTR».
4. Optionally enrich the step plan via Claude 4.7 JSON Mode into an actionable playbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategyJobStatus(StrEnum):
    """Lifecycle of an async AI Strategy job."""

    QUEUED = "queued"
    COMPARING = "comparing"
    PLANNING = "planning"
    COMPLETED = "completed"
    FAILED = "failed"


class RecommendationPriority(StrEnum):
    """How urgently the seller should apply a killer step."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StrategyActionType(StrEnum):
    """Ordered killer actions: background first → title last."""

    REPLACE_BACKGROUND = "replace_background"
    RESTRUCTURE_FIRST_SLIDE = "restructure_first_slide"
    ADD_INFOGRAPHIC = "add_infographic"
    ADJUST_CONTRAST_ACCENTS = "adjust_contrast_accents"
    REWRITE_OFFER = "rewrite_offer"
    UPDATE_PRICE_BADGE = "update_price_badge"
    CHANGE_TITLE = "change_title"


# Canonical execution order for the step-by-step plan.
ACTION_STEP_ORDER: tuple[StrategyActionType, ...] = (
    StrategyActionType.REPLACE_BACKGROUND,
    StrategyActionType.RESTRUCTURE_FIRST_SLIDE,
    StrategyActionType.ADD_INFOGRAPHIC,
    StrategyActionType.ADJUST_CONTRAST_ACCENTS,
    StrategyActionType.REWRITE_OFFER,
    StrategyActionType.UPDATE_PRICE_BADGE,
    StrategyActionType.CHANGE_TITLE,
)

_ACTION_LABELS_RU: dict[StrategyActionType, str] = {
    StrategyActionType.REPLACE_BACKGROUND: "фон",
    StrategyActionType.RESTRUCTURE_FIRST_SLIDE: "первый слайд / pain-hook",
    StrategyActionType.ADD_INFOGRAPHIC: "инфографику",
    StrategyActionType.ADJUST_CONTRAST_ACCENTS: "контрастные акценты",
    StrategyActionType.REWRITE_OFFER: "оффер",
    StrategyActionType.UPDATE_PRICE_BADGE: "ценовой бейдж",
    StrategyActionType.CHANGE_TITLE: "заголовок",
}

_ACTION_FIELD: dict[StrategyActionType, str] = {
    StrategyActionType.REPLACE_BACKGROUND: "background_style",
    StrategyActionType.RESTRUCTURE_FIRST_SLIDE: "first_slide_pain_hook",
    StrategyActionType.ADD_INFOGRAPHIC: "infographic_structure",
    StrategyActionType.ADJUST_CONTRAST_ACCENTS: "contrast_accents",
    StrategyActionType.REWRITE_OFFER: "offer_text",
    StrategyActionType.UPDATE_PRICE_BADGE: "price_badge",
    StrategyActionType.CHANGE_TITLE: "title",
}

# Relative weight of each dimension when attributing CTR lift across gaps.
_ACTION_CTR_WEIGHT: dict[StrategyActionType, float] = {
    StrategyActionType.REPLACE_BACKGROUND: 1.2,
    StrategyActionType.RESTRUCTURE_FIRST_SLIDE: 1.4,
    StrategyActionType.ADD_INFOGRAPHIC: 1.1,
    StrategyActionType.ADJUST_CONTRAST_ACCENTS: 0.9,
    StrategyActionType.REWRITE_OFFER: 1.0,
    StrategyActionType.UPDATE_PRICE_BADGE: 0.7,
    StrategyActionType.CHANGE_TITLE: 1.3,
}


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for AI Strategy payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class StrategyCompareConfig(StrictDomainModel):
    """Tunable thresholds for user-vs-leader comparison."""

    min_ctr_lift_pct: float = Field(default=5.0, ge=0.0, le=500.0)
    min_absolute_ctr_gap: float = Field(default=0.5, ge=0.0, le=100.0)
    max_recommendations: int = Field(default=7, ge=1, le=20)
    require_leader_ctr_advantage: bool = True

    @model_validator(mode="after")
    def _validate_bands(self) -> StrategyCompareConfig:
        if self.min_ctr_lift_pct < 0 or self.min_absolute_ctr_gap < 0:
            raise ValueError("CTR thresholds cannot be negative.")
        return self


class StrategyCardSnapshot(StrictDomainModel):
    """Seller or niche-leader card snapshot used for killer comparison."""

    sku: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    niche_key: str = Field(min_length=1, max_length=128)
    background_style: str | None = Field(default=None, max_length=256)
    first_slide_pain_hook: str | None = Field(default=None, max_length=500)
    infographic_structure: str | None = Field(default=None, max_length=500)
    contrast_accents: str | None = Field(default=None, max_length=256)
    offer_text: str | None = Field(default=None, max_length=500)
    price_badge: str | None = Field(default=None, max_length=128)
    ctr_pct: float = Field(ge=0.0, le=100.0)
    conversion_rate_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    review_count: int = Field(default=0, ge=0, le=10_000_000)
    rank: int | None = Field(default=None, ge=1, le=10_000)
    image_urls: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("sku", "title", "niche_key", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "background_style",
        "first_slide_pain_hook",
        "infographic_structure",
        "contrast_accents",
        "offer_text",
        "price_badge",
        mode="before",
    )
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("image_urls", mode="before")
    @classmethod
    def _clean_urls(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("image_urls must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("image_urls items must be strings.")
            text = item.strip()
            if text:
                cleaned.append(text[:2048])
        return cleaned[:12]


class FeatureDelta(StrictDomainModel):
    """One differing dimension between user card and niche leader."""

    action_type: StrategyActionType
    step_order: int = Field(ge=1, le=20)
    feature_label: str = Field(min_length=1, max_length=128)
    user_value: str | None = Field(default=None, max_length=500)
    leader_value: str | None = Field(default=None, max_length=500)
    attributed_ctr_lift_pct: float = Field(ge=0.0, le=500.0)
    rationale: str = Field(min_length=1, max_length=500)
    priority: RecommendationPriority
    gap_score: float = Field(ge=0.0, le=100.0)


class KillerRecommendation(StrictDomainModel):
    """One actionable step in the killer playbook."""

    step_number: int = Field(ge=1, le=20)
    action_type: StrategyActionType
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=800)
    rationale: str = Field(min_length=1, max_length=500)
    attributed_ctr_lift_pct: float = Field(ge=0.0, le=500.0)
    priority: RecommendationPriority
    user_current: str | None = Field(default=None, max_length=500)
    leader_reference: str | None = Field(default=None, max_length=500)
    expected_impact: str = Field(min_length=1, max_length=300)


class ClaudeStrategyEnrichment(StrictDomainModel):
    """Claude JSON enrichment for one killer step."""

    action_type: StrategyActionType
    refined_title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=800)
    rationale: str = Field(min_length=1, max_length=500)
    expected_impact: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)


class StrategyCompareReport(StrictDomainModel):
    """Deterministic pre-Claude comparison result."""

    marketplace: str = Field(min_length=1, max_length=32)
    niche_key: str = Field(min_length=1, max_length=128)
    config: StrategyCompareConfig
    user_sku: str = Field(min_length=1, max_length=64)
    leader_sku: str = Field(min_length=1, max_length=64)
    user_ctr_pct: float = Field(ge=0.0, le=100.0)
    leader_ctr_pct: float = Field(ge=0.0, le=100.0)
    total_ctr_lift_pct: float = Field(ge=-100.0, le=500.0)
    deltas: list[FeatureDelta] = Field(default_factory=list)
    recommendations: list[KillerRecommendation] = Field(default_factory=list)
    compare_notes: list[str] = Field(default_factory=list, max_length=40)


class StrategyPlanResult(StrictDomainModel):
    """Final AI Strategy output: step-by-step killer plan with CTR rationale."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    marketplace: str = Field(min_length=1, max_length=32)
    niche_key: str = Field(min_length=1, max_length=128)
    user_sku: str = Field(min_length=1, max_length=64)
    leader_sku: str = Field(min_length=1, max_length=64)
    total_ctr_lift_pct: float = Field(ge=-100.0, le=500.0)
    recommendations: list[KillerRecommendation] = Field(default_factory=list)
    enrichments: list[ClaudeStrategyEnrichment] = Field(default_factory=list)
    executive_summary: str = Field(min_length=1, max_length=800)
    model_name: str = Field(min_length=1, max_length=128)
    confidence_score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list, max_length=40)


class StrategyEnqueueRequest(StrictDomainModel):
    """API/domain request to run AI Strategy against a niche leader."""

    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    user_card: StrategyCardSnapshot
    leader_card: StrategyCardSnapshot
    compare_config: StrategyCompareConfig | None = None

    @field_validator("marketplace", "niche_key", mode="before")
    @classmethod
    def _strip_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _same_niche(self) -> StrategyEnqueueRequest:
        user_niche = self.user_card.niche_key.strip().casefold()
        leader_niche = self.leader_card.niche_key.strip().casefold()
        request_niche = self.niche_key.strip().casefold()
        if user_niche != request_niche or leader_niche != request_niche:
            raise ValueError(
                "user_card.niche_key and leader_card.niche_key must match niche_key."
            )
        if self.user_card.sku.strip().casefold() == self.leader_card.sku.strip().casefold():
            raise ValueError("user_card.sku and leader_card.sku must differ.")
        return self


@dataclass(frozen=True, slots=True)
class StrategyJobView:
    """Projection of a persisted AI Strategy job."""

    id: UUID
    user_id: UUID
    status: StrategyJobStatus
    celery_task_id: str | None
    niche_key: str
    marketplace: str
    user_card_payload: dict[str, Any]
    leader_card_payload: dict[str, Any]
    compare_config: dict[str, Any]
    compare_report: dict[str, Any] | None
    plan_result: dict[str, Any] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


STRATEGY_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "executive_summary",
        "steps",
        "reasoning_trace",
    ],
    "properties": {
        "executive_summary": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "action_type",
                    "refined_title",
                    "instruction",
                    "rationale",
                    "expected_impact",
                    "confidence",
                ],
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": [a.value for a in StrategyActionType],
                    },
                    "refined_title": {"type": "string"},
                    "instruction": {"type": "string"},
                    "rationale": {"type": "string"},
                    "expected_impact": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "reasoning_trace": {"type": "string"},
    },
}


_STRATEGY_SYSTEM_PROMPT = (
    "You are AI Strategy — a marketplace card strategist for Wildberries and Ozon. "
    "You receive a deterministic comparison of the seller's card vs the niche leader. "
    "Produce a step-by-step killer plan ordered from background replacement to title change. "
    "Every recommendation MUST keep a CTR-backed rationale in Russian of the form "
    "«Конкурент использует … и имеет на N% выше CTR». "
    "Do not invent CTR numbers — reuse attributed_ctr_lift_pct from the input. "
    "Return ONLY valid JSON matching the schema."
)


def strategy_system_prompt() -> str:
    return _STRATEGY_SYSTEM_PROMPT


def action_label_ru(action: StrategyActionType) -> str:
    return _ACTION_LABELS_RU[action]


def compute_ctr_lift_pct(*, user_ctr_pct: float, leader_ctr_pct: float) -> float:
    """Relative CTR advantage of the leader over the user (percent points lift)."""

    if user_ctr_pct <= 0:
        if leader_ctr_pct <= 0:
            return 0.0
        return round(leader_ctr_pct * 10.0, 2)  # treat absolute as strong signal
    lift = ((leader_ctr_pct - user_ctr_pct) / user_ctr_pct) * 100.0
    return round(lift, 2)


def build_ctr_rationale(*, feature_label: str, ctr_lift_pct: float) -> str:
    """Canonical Russian CTR rationale for each killer recommendation."""

    pct = int(round(abs(ctr_lift_pct)))
    if pct < 1:
        pct = 1
    label = feature_label.strip() or "это"
    return f"Конкурент использует {label} и имеет на {pct}% выше CTR"


def priority_from_lift(ctr_lift_pct: float) -> RecommendationPriority:
    if ctr_lift_pct >= 25.0:
        return RecommendationPriority.CRITICAL
    if ctr_lift_pct >= 15.0:
        return RecommendationPriority.HIGH
    if ctr_lift_pct >= 8.0:
        return RecommendationPriority.MEDIUM
    return RecommendationPriority.LOW


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned or None


def _values_differ(user_value: str | None, leader_value: str | None) -> bool:
    u = (_normalize_text(user_value) or "").casefold()
    l = (_normalize_text(leader_value) or "").casefold()
    if not l and not u:
        return False
    if l and not u:
        return True
    if u and not l:
        return False
    return u != l


def _field_value(card: StrategyCardSnapshot, field: str) -> str | None:
    return getattr(card, field)


def _gap_score(*, attributed_lift: float, total_lift: float, weight: float) -> float:
    if total_lift <= 0:
        return round(min(weight * 20.0, 100.0), 2)
    share = attributed_lift / total_lift
    raw = share * 70.0 + weight * 10.0
    return round(min(max(raw, 0.0), 100.0), 2)


def _deterministic_instruction(
    *,
    action: StrategyActionType,
    leader_value: str | None,
) -> str:
    ref = _normalize_text(leader_value) or "как у лидера ниши"
    templates: dict[StrategyActionType, str] = {
        StrategyActionType.REPLACE_BACKGROUND: (
            f"Замените фон карточки на стиль «{ref}», чтобы выровняться с лидером в слепой выдаче."
        ),
        StrategyActionType.RESTRUCTURE_FIRST_SLIDE: (
            f"Пересоберите первый слайд вокруг pain-hook «{ref}» — лидер закрывает боль сразу."
        ),
        StrategyActionType.ADD_INFOGRAPHIC: (
            f"Добавьте/перестройте инфографику по структуре «{ref}»."
        ),
        StrategyActionType.ADJUST_CONTRAST_ACCENTS: (
            f"Усильте контрастные акценты: ориентир лидера — «{ref}»."
        ),
        StrategyActionType.REWRITE_OFFER: (
            f"Перепишите оффер ближе к формулировке лидера: «{ref}»."
        ),
        StrategyActionType.UPDATE_PRICE_BADGE: (
            f"Обновите ценовой бейдж по образцу лидера: «{ref}»."
        ),
        StrategyActionType.CHANGE_TITLE: (
            f"Измените заголовок карточки, ориентируясь на лидера: «{ref}»."
        ),
    }
    return templates[action]


def _deterministic_title(action: StrategyActionType) -> str:
    titles: dict[StrategyActionType, str] = {
        StrategyActionType.REPLACE_BACKGROUND: "Замена фона",
        StrategyActionType.RESTRUCTURE_FIRST_SLIDE: "Перестройка первого слайда",
        StrategyActionType.ADD_INFOGRAPHIC: "Инфографика как у лидера",
        StrategyActionType.ADJUST_CONTRAST_ACCENTS: "Контрастные акценты",
        StrategyActionType.REWRITE_OFFER: "Перепись оффера",
        StrategyActionType.UPDATE_PRICE_BADGE: "Ценовой бейдж",
        StrategyActionType.CHANGE_TITLE: "Изменение заголовка",
    }
    return titles[action]


def compare_user_vs_leader(
    *,
    marketplace: str,
    niche_key: str,
    user_card: StrategyCardSnapshot,
    leader_card: StrategyCardSnapshot,
    config: StrategyCompareConfig | None = None,
) -> StrategyCompareReport:
    """Diff seller card vs niche leader → ordered killer steps with CTR rationale."""

    cfg = config or StrategyCompareConfig()
    notes: list[str] = []
    marketplace_norm = marketplace.strip().lower()
    niche = niche_key.strip()

    total_lift = compute_ctr_lift_pct(
        user_ctr_pct=user_card.ctr_pct,
        leader_ctr_pct=leader_card.ctr_pct,
    )
    absolute_gap = leader_card.ctr_pct - user_card.ctr_pct

    if cfg.require_leader_ctr_advantage and (
        total_lift < cfg.min_ctr_lift_pct and absolute_gap < cfg.min_absolute_ctr_gap
    ):
        notes.append(
            f"Лидер не даёт достаточного CTR-преимущества "
            f"(lift={total_lift:.1f}%, gap={absolute_gap:.2f} п.п.) — план пуст."
        )
        return StrategyCompareReport(
            marketplace=marketplace_norm,
            niche_key=niche,
            config=cfg,
            user_sku=user_card.sku,
            leader_sku=leader_card.sku,
            user_ctr_pct=user_card.ctr_pct,
            leader_ctr_pct=leader_card.ctr_pct,
            total_ctr_lift_pct=total_lift,
            compare_notes=notes,
        )

    differing: list[StrategyActionType] = []
    for action in ACTION_STEP_ORDER:
        field = _ACTION_FIELD[action]
        user_val = _field_value(user_card, field)
        leader_val = _field_value(leader_card, field)
        if _values_differ(user_val, leader_val):
            differing.append(action)

    if not differing:
        notes.append(
            "Визуал и копирайт совпадают с лидером по ключевым измерениям — "
            "killer-дельта не найдена."
        )
        return StrategyCompareReport(
            marketplace=marketplace_norm,
            niche_key=niche,
            config=cfg,
            user_sku=user_card.sku,
            leader_sku=leader_card.sku,
            user_ctr_pct=user_card.ctr_pct,
            leader_ctr_pct=leader_card.ctr_pct,
            total_ctr_lift_pct=total_lift,
            compare_notes=notes,
        )

    # Attribute total CTR lift across differing dimensions by relative weight.
    weight_sum = sum(_ACTION_CTR_WEIGHT[a] for a in differing)
    effective_lift = max(total_lift, absolute_gap * 10.0 if absolute_gap > 0 else 0.0)
    if effective_lift <= 0:
        # Still emit plan when leader wins on rank but CTR is flat — soft signal.
        effective_lift = 10.0
        notes.append(
            "CTR почти равен; используем мягкую атрибуцию lift=10% по отличающимся фичам."
        )

    deltas: list[FeatureDelta] = []
    for idx, action in enumerate(differing, start=1):
        field = _ACTION_FIELD[action]
        user_val = _normalize_text(_field_value(user_card, field))
        leader_val = _normalize_text(_field_value(leader_card, field))
        weight = _ACTION_CTR_WEIGHT[action]
        attributed = round(effective_lift * (weight / weight_sum), 2)
        label = action_label_ru(action)
        rationale = build_ctr_rationale(
            feature_label=label,
            ctr_lift_pct=attributed,
        )
        deltas.append(
            FeatureDelta(
                action_type=action,
                step_order=idx,
                feature_label=label,
                user_value=user_val,
                leader_value=leader_val,
                attributed_ctr_lift_pct=attributed,
                rationale=rationale,
                priority=priority_from_lift(attributed),
                gap_score=_gap_score(
                    attributed_lift=attributed,
                    total_lift=effective_lift,
                    weight=weight,
                ),
            )
        )

    deltas.sort(key=lambda d: ACTION_STEP_ORDER.index(d.action_type))
    truncated = deltas[: cfg.max_recommendations]
    if len(deltas) > cfg.max_recommendations:
        notes.append(
            f"Найдено {len(deltas)} дельт; отдаём топ-{cfg.max_recommendations} "
            f"в порядке background→title."
        )

    recommendations: list[KillerRecommendation] = []
    for step_number, delta in enumerate(truncated, start=1):
        recommendations.append(
            KillerRecommendation(
                step_number=step_number,
                action_type=delta.action_type,
                title=_deterministic_title(delta.action_type),
                instruction=_deterministic_instruction(
                    action=delta.action_type,
                    leader_value=delta.leader_value,
                ),
                rationale=delta.rationale,
                attributed_ctr_lift_pct=delta.attributed_ctr_lift_pct,
                priority=delta.priority,
                user_current=delta.user_value,
                leader_reference=delta.leader_value,
                expected_impact=(
                    f"Ожидаемый вклад в CTR: ≈{delta.attributed_ctr_lift_pct:.0f}% "
                    f"от преимущества лидера."
                ),
            )
        )

    notes.append(
        f"Сформирован пошаговый план из {len(recommendations)} шагов "
        f"(CTR lift лидера {total_lift:.1f}%)."
    )

    return StrategyCompareReport(
        marketplace=marketplace_norm,
        niche_key=niche,
        config=cfg,
        user_sku=user_card.sku,
        leader_sku=leader_card.sku,
        user_ctr_pct=user_card.ctr_pct,
        leader_ctr_pct=leader_card.ctr_pct,
        total_ctr_lift_pct=total_lift,
        deltas=truncated,
        recommendations=recommendations,
        compare_notes=notes,
    )


def build_strategy_plan_prompt(*, compare_report: StrategyCompareReport) -> str:
    """User prompt for Claude enrichment of the killer step plan."""

    lines: list[str] = [
        f"Маркетплейс: {compare_report.marketplace}. Ниша: {compare_report.niche_key}.",
        f"Карточка продавца: {compare_report.user_sku} (CTR {compare_report.user_ctr_pct}%).",
        f"Лидер ниши: {compare_report.leader_sku} (CTR {compare_report.leader_ctr_pct}%).",
        f"Общий CTR lift лидера: {compare_report.total_ctr_lift_pct:.1f}%.",
        "Составь пошаговый план от замены фона до изменения заголовка.",
        "Каждый шаг обязан сохранить rationale формата: "
        "«Конкурент использует … и имеет на N% выше CTR» (N из attributed_ctr_lift_pct).",
        "Шаги:",
    ]
    for rec in compare_report.recommendations:
        lines.append(
            f"{rec.step_number}. action_type={rec.action_type.value}; "
            f"title={rec.title}; lift={rec.attributed_ctr_lift_pct}%; "
            f"rationale={rec.rationale}; "
            f"user={rec.user_current or '—'}; leader={rec.leader_reference or '—'}; "
            f"instruction={rec.instruction}"
        )
    lines.append(
        "Сначала рассуждай в reasoning_trace, затем заполни JSON. "
        "action_type в ответе должен совпадать с входным."
    )
    return " ".join(lines)


def build_plan_result(
    *,
    compare_report: StrategyCompareReport,
    enrichments: list[ClaudeStrategyEnrichment],
    model_name: str,
    executive_summary: str | None = None,
) -> StrategyPlanResult:
    """Merge deterministic steps with Claude enrichments into final plan."""

    notes = list(compare_report.compare_notes)
    enrichment_by_action = {e.action_type: e for e in enrichments}

    recommendations: list[KillerRecommendation] = []
    for rec in compare_report.recommendations:
        enriched = enrichment_by_action.get(rec.action_type)
        if enriched is not None:
            # Preserve CTR rationale if Claude drifted away from the canonical form.
            rationale = enriched.rationale
            if "выше CTR" not in rationale:
                rationale = rec.rationale
            recommendations.append(
                KillerRecommendation(
                    step_number=rec.step_number,
                    action_type=rec.action_type,
                    title=enriched.refined_title,
                    instruction=enriched.instruction,
                    rationale=rationale,
                    attributed_ctr_lift_pct=rec.attributed_ctr_lift_pct,
                    priority=rec.priority,
                    user_current=rec.user_current,
                    leader_reference=rec.leader_reference,
                    expected_impact=enriched.expected_impact,
                )
            )
        else:
            recommendations.append(rec)

    if executive_summary and executive_summary.strip():
        summary = executive_summary.strip()[:800]
    elif recommendations:
        summary = (
            f"План из {len(recommendations)} шагов против лидера "
            f"{compare_report.leader_sku}: CTR выше на "
            f"{max(compare_report.total_ctr_lift_pct, 0):.0f}%. "
            f"Старт — {recommendations[0].title.lower()}, финиш — "
            f"{recommendations[-1].title.lower()}."
        )
    else:
        summary = "Killer-рекомендаций нет: дельта к лидеру недостаточна."

    confidence = 0.0
    if enrichments:
        confidence = sum(e.confidence for e in enrichments) / len(enrichments)
    elif recommendations:
        # Deterministic confidence from average gap_score of underlying deltas.
        if compare_report.deltas:
            confidence = min(
                sum(d.gap_score for d in compare_report.deltas)
                / (100.0 * len(compare_report.deltas)),
                1.0,
            )
        else:
            confidence = 0.55
        notes.append(
            "Claude enrichment пропущен — план по детерминированному сравнению."
        )

    return StrategyPlanResult(
        marketplace=compare_report.marketplace,
        niche_key=compare_report.niche_key,
        user_sku=compare_report.user_sku,
        leader_sku=compare_report.leader_sku,
        total_ctr_lift_pct=compare_report.total_ctr_lift_pct,
        recommendations=recommendations,
        enrichments=list(enrichments),
        executive_summary=summary,
        model_name=model_name.strip() or "deterministic",
        confidence_score=round(confidence, 4),
        notes=notes[:40],
    )


def dump_compare_report(report: StrategyCompareReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


def dump_plan_result(result: StrategyPlanResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def redis_strategy_key(job_id: UUID, stage: str) -> str:
    """Redis key for an intermediate AI Strategy stage payload."""

    return f"claude:ai_strategy:{job_id}:{stage}"
