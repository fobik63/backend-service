"""Style-preset analytics domain: aggregates and AI insight contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Strict frozen domain contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InsightMetric(StrEnum):
    """Marketplace metric an insight claims to influence."""

    CTR = "ctr"
    CONVERSION = "conversion"
    ATTENTION = "attention"
    TRUST = "trust"


class InsightPriority(StrEnum):
    """Recommendation urgency for the frontend."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StyleSelectionAggregate(DomainModel):
    """Counted selection of one niche + slide + style triple."""

    niche_key: str = Field(min_length=1, max_length=64)
    slide_key: str = Field(min_length=1, max_length=64)
    selected_style: str = Field(min_length=1, max_length=500)
    selection_count: int = Field(ge=0)


class NicheSelectionAggregate(DomainModel):
    """Counted selections rolled up by niche."""

    niche_key: str = Field(min_length=1, max_length=64)
    selection_count: int = Field(ge=0)


class StyleAiInsight(DomainModel):
    """Single AI-style recommendation tied to a preset."""

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    metric: InsightMetric
    estimated_lift_percent: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1000)


class TopStylePresetInsight(DomainModel):
    """Popular preset row enriched with an AI insight."""

    rank: int = Field(ge=1)
    niche_key: str = Field(min_length=1, max_length=64)
    niche_title: str = Field(min_length=1, max_length=128)
    slide_key: str = Field(min_length=1, max_length=64)
    selected_style: str = Field(min_length=1, max_length=500)
    selection_count: int = Field(ge=0)
    share_percent: float = Field(ge=0.0, le=100.0)
    ai_insight: StyleAiInsight


class NicheBreakdownItem(DomainModel):
    """Niche popularity slice for analytics charts."""

    niche_key: str = Field(min_length=1, max_length=64)
    niche_title: str = Field(min_length=1, max_length=128)
    selection_count: int = Field(ge=0)
    share_percent: float = Field(ge=0.0, le=100.0)
    top_style: str | None = Field(default=None, max_length=500)


class StyleAiRecommendation(DomainModel):
    """Actionable top-level AI recommendation for the product UI."""

    code: str = Field(min_length=1, max_length=64)
    priority: InsightPriority
    message: str = Field(min_length=1, max_length=500)
    niche_key: str = Field(min_length=1, max_length=64)
    selected_style: str = Field(min_length=1, max_length=500)
    slide_key: str = Field(min_length=1, max_length=64)
    metric: InsightMetric
    estimated_lift_percent: float = Field(ge=0.0, le=100.0)


class StylePresetAnalytics(DomainModel):
    """Full analytics payload for GET style-preset insights."""

    generated_at: datetime
    period_days: int = Field(ge=1, le=365)
    total_selections: int = Field(ge=0)
    unique_presets: int = Field(ge=0)
    top_presets: tuple[TopStylePresetInsight, ...]
    by_niche: tuple[NicheBreakdownItem, ...]
    ai_recommendations: tuple[StyleAiRecommendation, ...]


# Baseline lift estimates by marketplace slide role (cover drives CTR hardest).
_SLIDE_BASE_LIFT: dict[str, tuple[InsightMetric, float]] = {
    "cover": (InsightMetric.CTR, 15.0),
    "lifestyle": (InsightMetric.CTR, 12.0),
    "macro": (InsightMetric.ATTENTION, 9.0),
    "technical": (InsightMetric.CONVERSION, 8.0),
    "trust": (InsightMetric.TRUST, 10.0),
    "model": (InsightMetric.CONVERSION, 11.0),
}

_METRIC_LABEL_RU: dict[InsightMetric, str] = {
    InsightMetric.CTR: "CTR",
    InsightMetric.CONVERSION: "конверсию",
    InsightMetric.ATTENTION: "внимание к карточке",
    InsightMetric.TRUST: "доверие к офферу",
}

_NICHE_TITLES_FALLBACK: dict[str, str] = {
    "perfume": "Парфюмерия",
    "clothing": "Одежда",
    "electronics": "Электроника",
    "generic": "Общий стиль",
}


def niche_display_title(niche_key: str, catalog_title: str | None = None) -> str:
    """Human-readable niche title for API responses."""

    if catalog_title and catalog_title.strip():
        return catalog_title.strip()
    return _NICHE_TITLES_FALLBACK.get(niche_key, niche_key)


def build_style_ai_insight(
    *,
    niche_key: str,
    niche_title: str,
    slide_key: str,
    selected_style: str,
    selection_count: int,
    total_selections: int,
    rank: int,
) -> StyleAiInsight:
    """Derive a deterministic AI insight from internal selection statistics.

    Lift is grounded in slide role + relative popularity share so the API can
    return messages like «Этот фон повышает CTR на 15%» without an external
    LLM round-trip on every analytics request.
    """

    metric, base_lift = _SLIDE_BASE_LIFT.get(
        slide_key,
        (InsightMetric.CTR, 7.0),
    )
    share = (selection_count / total_selections) if total_selections > 0 else 0.0
    popularity_boost = min(8.0, round(share * 40.0, 1))
    rank_penalty = max(0.0, (rank - 1) * 1.5)
    estimated_lift = round(max(3.0, min(28.0, base_lift + popularity_boost - rank_penalty)), 1)
    confidence = round(
        min(0.95, 0.55 + share * 0.9 + max(0.0, 0.12 - (rank - 1) * 0.03)),
        2,
    )
    metric_label = _METRIC_LABEL_RU[metric]
    if metric is InsightMetric.CTR:
        message = f"Этот фон повышает CTR на {estimated_lift:g}%"
    else:
        message = f"Этот стиль повышает {metric_label} на {estimated_lift:g}%"

    rationale = (
        f"Пресет «{selected_style}» ({slide_key}) в нише «{niche_title}» "
        f"выбран {selection_count} раз"
        + (
            f" ({share * 100:.1f}% всех выборов за период)."
            if total_selections > 0
            else "."
        )
        + " Оценка построена на внутренней частоте выбора и роли слайда в выдаче."
    )
    return StyleAiInsight(
        code=f"{metric.value}_lift_{slide_key}",
        message=message,
        metric=metric,
        estimated_lift_percent=estimated_lift,
        confidence=confidence,
        rationale=rationale,
    )


def build_style_preset_analytics(
    *,
    generated_at: datetime,
    period_days: int,
    style_rows: list[StyleSelectionAggregate],
    niche_rows: list[NicheSelectionAggregate],
    niche_titles: dict[str, str],
    top_limit: int = 10,
) -> StylePresetAnalytics:
    """Assemble the public analytics DTO from repository aggregates."""

    total_selections = sum(row.selection_count for row in style_rows)
    unique_presets = len(style_rows)
    ranked = sorted(
        style_rows,
        key=lambda row: (-row.selection_count, row.niche_key, row.selected_style),
    )[: max(1, top_limit)]

    top_presets: list[TopStylePresetInsight] = []
    recommendations: list[StyleAiRecommendation] = []
    for index, row in enumerate(ranked, start=1):
        title = niche_display_title(row.niche_key, niche_titles.get(row.niche_key))
        share = (
            round((row.selection_count / total_selections) * 100.0, 1)
            if total_selections > 0
            else 0.0
        )
        insight = build_style_ai_insight(
            niche_key=row.niche_key,
            niche_title=title,
            slide_key=row.slide_key,
            selected_style=row.selected_style,
            selection_count=row.selection_count,
            total_selections=total_selections,
            rank=index,
        )
        top_presets.append(
            TopStylePresetInsight(
                rank=index,
                niche_key=row.niche_key,
                niche_title=title,
                slide_key=row.slide_key,
                selected_style=row.selected_style,
                selection_count=row.selection_count,
                share_percent=share,
                ai_insight=insight,
            )
        )
        if index <= 3 and row.selection_count > 0:
            priority = (
                InsightPriority.HIGH
                if index == 1
                else InsightPriority.MEDIUM
                if index == 2
                else InsightPriority.LOW
            )
            insight_tail = (
                insight.message[0].lower() + insight.message[1:]
                if insight.message
                else insight.message
            )
            recommendations.append(
                StyleAiRecommendation(
                    code=f"recommend_{row.niche_key}_{row.slide_key}",
                    priority=priority,
                    message=(
                        f"Для ниши «{title}» используйте стиль «{row.selected_style}» "
                        f"— {insight_tail}"
                    ),
                    niche_key=row.niche_key,
                    selected_style=row.selected_style,
                    slide_key=row.slide_key,
                    metric=insight.metric,
                    estimated_lift_percent=insight.estimated_lift_percent,
                )
            )

    niche_total = sum(row.selection_count for row in niche_rows) or total_selections
    top_style_by_niche: dict[str, str] = {}
    for row in sorted(style_rows, key=lambda r: -r.selection_count):
        top_style_by_niche.setdefault(row.niche_key, row.selected_style)

    by_niche: list[NicheBreakdownItem] = []
    for row in sorted(niche_rows, key=lambda r: -r.selection_count):
        title = niche_display_title(row.niche_key, niche_titles.get(row.niche_key))
        share = (
            round((row.selection_count / niche_total) * 100.0, 1)
            if niche_total > 0
            else 0.0
        )
        by_niche.append(
            NicheBreakdownItem(
                niche_key=row.niche_key,
                niche_title=title,
                selection_count=row.selection_count,
                share_percent=share,
                top_style=top_style_by_niche.get(row.niche_key),
            )
        )

    return StylePresetAnalytics(
        generated_at=generated_at,
        period_days=period_days,
        total_selections=total_selections,
        unique_presets=unique_presets,
        top_presets=tuple(top_presets),
        by_niche=tuple(by_niche),
        ai_recommendations=tuple(recommendations),
    )
