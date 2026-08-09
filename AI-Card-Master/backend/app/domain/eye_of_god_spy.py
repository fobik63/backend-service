"""Eye of God spy analytics: TOP-N competitor discovery + dashboard aggregate.

User-facing spy tool (editor «Глаз Бога»):
1. Resolve competitor article / URL.
2. Discover TOP-N similar marketplace cards.
3. Deep-scrape + Claude audit (via competitor_audit job).
4. Aggregate badges, triggers, keywords, visual hooks + AI recommendation.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.competitor_audit import (
    MAX_CARDS_PER_JOB,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
)
from app.domain.estimated_sales import estimate_purchases, estimate_revenue_rub

DEFAULT_TOP_COMPETITORS = 10
MAX_TOP_COMPETITORS = MAX_CARDS_PER_JOB
MIN_TOP_COMPETITORS = 3

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{3,}", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "для",
        "или",
        "the",
        "and",
        "with",
        "без",
        "при",
        "над",
        "под",
        "это",
        "как",
        "что",
        "все",
        "ваш",
        "наш",
        "шт",
        "мм",
        "см",
        "мл",
        "кг",
        "г",
        "набор",
        "упаковка",
        "товар",
        "карта",
        "wildberries",
        "ozon",
    }
)


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PersistedDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompetitorDiscoveryHit(PersistedDomainModel):
    """One competitor candidate from marketplace search / similar catalog."""

    rank: int = Field(ge=1, le=MAX_TOP_COMPETITORS)
    article: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=12, max_length=2048)
    marketplace: CompetitorMarketplace
    title: str | None = Field(default=None, max_length=500)
    brand: str | None = Field(default=None, max_length=256)
    price_rub: float | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    feedbacks: int | None = Field(default=None, ge=0)


class EyeOfGodSpyEnqueueRequest(StrictDomainModel):
    """Resolve article/URL → discover TOP-N competitors → enqueue audit."""

    input: str = Field(min_length=1, max_length=2048)
    platform: Literal["auto", "wb", "ozon"] = "auto"
    limit: int = Field(default=DEFAULT_TOP_COMPETITORS, ge=MIN_TOP_COMPETITORS, le=MAX_TOP_COMPETITORS)

    @field_validator("input", mode="before")
    @classmethod
    def _strip_input(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class FrequencyItem(PersistedDomainModel):
    """Ranked phrase / keyword with occurrence count across competitors."""

    text: str = Field(min_length=1, max_length=240)
    count: int = Field(ge=1)
    share_percent: float = Field(ge=0, le=100)
    examples: list[str] = Field(default_factory=list, max_length=5)


class EyeOfGodCompetitorCardSummary(PersistedDomainModel):
    """Compact competitor row for the spy dashboard list."""

    rank: int = Field(ge=1, le=MAX_TOP_COMPETITORS)
    article: str
    marketplace: str
    title: str | None = None
    brand: str | None = None
    url: str | None = None
    price_rub: float | None = None
    feedbacks: int | None = None
    # Heuristic GMV until MPSTATS/MarketGuru: feedbacks × ~12.5 × price.
    estimated_purchases: int | None = None
    estimated_revenue_rub: float | None = None
    is_niche_revenue_leader: bool = False
    conversion_triggers: list[str] = Field(default_factory=list, max_length=8)
    weaknesses: list[str] = Field(default_factory=list, max_length=8)
    advice_reliability_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class EyeOfGodSpyDashboard(PersistedDomainModel):
    """Aggregated spy dashboard for the editor «Глаз Бога» widget."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    seed_article: str = Field(min_length=1, max_length=64)
    seed_marketplace: str = Field(min_length=1, max_length=32)
    seed_title: str | None = Field(default=None, max_length=500)
    competitors_analyzed: int = Field(ge=0, le=MAX_TOP_COMPETITORS)
    competitors: list[EyeOfGodCompetitorCardSummary] = Field(
        default_factory=list,
        max_length=MAX_TOP_COMPETITORS,
    )
    badge_patterns: list[FrequencyItem] = Field(default_factory=list, max_length=20)
    strong_triggers: list[FrequencyItem] = Field(default_factory=list, max_length=20)
    frequent_keywords: list[FrequencyItem] = Field(default_factory=list, max_length=30)
    visual_hooks: list[str] = Field(default_factory=list, max_length=20)
    ai_recommendation: str = Field(default="", max_length=4000)
    generator_prompt: str = Field(default="", max_length=4000)
    notes: list[str] = Field(default_factory=list, max_length=20)


def _norm_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _frequency_items(
    phrases: list[str],
    *,
    total_cards: int,
    limit: int,
) -> list[FrequencyItem]:
    counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for raw in phrases:
        phrase = _norm_phrase(raw)
        if len(phrase) < 2:
            continue
        key = phrase.casefold()
        counter[key] += 1
        bucket = examples.setdefault(key, [])
        if phrase not in bucket and len(bucket) < 5:
            bucket.append(phrase)

    denom = max(total_cards, 1)
    items: list[FrequencyItem] = []
    for key, count in counter.most_common(limit):
        label = examples.get(key, [key])[0]
        items.append(
            FrequencyItem(
                text=label[:240],
                count=count,
                share_percent=min(100.0, round(100.0 * count / denom, 1)),
                examples=examples.get(key, [])[:5],
            )
        )
    return items


def _extract_keywords(*texts: str | None, limit: int = 40) -> list[str]:
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _WORD_RE.findall(text.casefold()):
            if match in _STOP_WORDS or match.isdigit():
                continue
            found.append(match)
            if len(found) >= limit:
                return found
    return found


def build_eye_of_god_dashboard(
    *,
    seed_article: str,
    seed_marketplace: CompetitorMarketplace | str,
    seed_title: str | None,
    discovery: list[CompetitorDiscoveryHit],
    scrape_cards: list[CompetitorCardScrapeResult],
    analysis_cards: list[CompetitorCardDeepAnalysis],
    notes: list[str] | None = None,
) -> EyeOfGodSpyDashboard:
    """Aggregate scrape + Claude audit into the spy dashboard JSON."""

    mp = (
        seed_marketplace.value
        if isinstance(seed_marketplace, CompetitorMarketplace)
        else str(seed_marketplace)
    )
    by_article_analysis = {card.article: card for card in analysis_cards}
    by_article_scrape = {card.article: card for card in scrape_cards}

    competitors: list[EyeOfGodCompetitorCardSummary] = []
    badge_phrases: list[str] = []
    trigger_phrases: list[str] = []
    keyword_phrases: list[str] = []
    visual_hooks: list[str] = []
    recommendation_parts: list[str] = []
    prompt_parts: list[str] = []

    ordered = discovery or [
        CompetitorDiscoveryHit(
            rank=i + 1,
            article=card.article,
            url=card.source_url,
            marketplace=card.marketplace,
            title=card.title,
            brand=card.brand,
        )
        for i, card in enumerate(scrape_cards[:MAX_TOP_COMPETITORS])
    ]

    for hit in ordered[:MAX_TOP_COMPETITORS]:
        analysis = by_article_analysis.get(hit.article)
        scrape = by_article_scrape.get(hit.article)
        title = (analysis.title if analysis else None) or hit.title or (
            scrape.title if scrape else None
        )
        brand = hit.brand or (scrape.brand if scrape else None)
        price = hit.price_rub
        if price is None and scrape and scrape.price_after_discount_kopecks:
            price = round(scrape.price_after_discount_kopecks / 100.0, 2)

        triggers = list(analysis.conversion_triggers[:8]) if analysis else []
        weaknesses = list(analysis.competitor_weaknesses[:8]) if analysis else []
        feedbacks = hit.feedbacks
        competitors.append(
            EyeOfGodCompetitorCardSummary(
                rank=hit.rank,
                article=hit.article,
                marketplace=hit.marketplace.value
                if isinstance(hit.marketplace, CompetitorMarketplace)
                else str(hit.marketplace),
                title=title,
                brand=brand,
                url=hit.url,
                price_rub=price,
                feedbacks=feedbacks,
                estimated_purchases=estimate_purchases(feedbacks),
                estimated_revenue_rub=estimate_revenue_rub(
                    feedbacks=feedbacks,
                    price_rub=price,
                ),
                conversion_triggers=triggers,
                weaknesses=weaknesses,
                advice_reliability_pct=(
                    float(analysis.advice_reliability_pct) if analysis else 0.0
                ),
            )
        )

        if analysis:
            blueprint = analysis.actionable_blueprint
            badge_phrases.extend(blueprint.pain_badges)
            badge_phrases.extend(blueprint.first_slide_offers)
            trigger_phrases.extend(analysis.conversion_triggers)
            visual = analysis.visual_audit
            if visual.first_slide_offer_layout:
                visual_hooks.append(_norm_phrase(visual.first_slide_offer_layout)[:240])
            visual_hooks.extend(_norm_phrase(z)[:240] for z in visual.blind_zones if z)
            visual_hooks.extend(
                _norm_phrase(c)[:80] for c in visual.color_palette[:4] if c
            )
            if blueprint.generator_prompt:
                prompt_parts.append(blueprint.generator_prompt.strip())
            if weaknesses:
                recommendation_parts.append(
                    f"Артикул {hit.article}: закрой слабости — "
                    + "; ".join(weaknesses[:3])
                )
            if blueprint.pain_badges:
                recommendation_parts.append(
                    f"Вынеси на плашки: {', '.join(blueprint.pain_badges[:4])}."
                )
            if blueprint.background:
                recommendation_parts.append(
                    f"Фон/атмосфера лучше их: {blueprint.background}"
                )

        if scrape:
            keyword_phrases.extend(
                _extract_keywords(scrape.title, scrape.description, scrape.brand)
            )
            for spec in scrape.specs[:12]:
                keyword_phrases.extend(_extract_keywords(spec.name, spec.value))

        if title:
            keyword_phrases.extend(_extract_keywords(title, brand))

    # Deduplicate visual hooks while preserving order.
    seen_hooks: set[str] = set()
    unique_hooks: list[str] = []
    for hook in visual_hooks:
        key = hook.casefold()
        if not hook or key in seen_hooks:
            continue
        seen_hooks.add(key)
        unique_hooks.append(hook)
        if len(unique_hooks) >= 20:
            break

    # Mark niche revenue leader (max heuristic GMV) for UI highlight.
    leader_revenue: float | None = None
    for card in competitors:
        if card.estimated_revenue_rub is None:
            continue
        if leader_revenue is None or card.estimated_revenue_rub > leader_revenue:
            leader_revenue = card.estimated_revenue_rub
    if leader_revenue is not None:
        for card in competitors:
            if card.estimated_revenue_rub == leader_revenue:
                card.is_niche_revenue_leader = True
                break

    total = max(len(competitors), 1)
    ai_recommendation = " ".join(recommendation_parts).strip()
    if not ai_recommendation and competitors:
        ai_recommendation = (
            "Соберите офферы конкурентов на первом слайде, усильте контраст плашек "
            "и закройте слепые зоны, которые повторяются у ТОП выдачи."
        )

    generator_prompt = ""
    if prompt_parts:
        # Prefer the highest-reliability card prompt, else first.
        best_idx = 0
        best_rel = -1.0
        for i, hit in enumerate(ordered[: len(prompt_parts)]):
            analysis = by_article_analysis.get(hit.article)
            rel = float(analysis.advice_reliability_pct) if analysis else 0.0
            if rel >= best_rel:
                best_rel = rel
                best_idx = min(i, len(prompt_parts) - 1)
        generator_prompt = prompt_parts[best_idx][:4000]

    return EyeOfGodSpyDashboard(
        seed_article=seed_article[:64],
        seed_marketplace=mp,
        seed_title=(seed_title or None),
        competitors_analyzed=len(competitors),
        competitors=competitors,
        badge_patterns=_frequency_items(badge_phrases, total_cards=total, limit=12),
        strong_triggers=_frequency_items(trigger_phrases, total_cards=total, limit=12),
        frequent_keywords=_frequency_items(keyword_phrases, total_cards=total, limit=20),
        visual_hooks=unique_hooks,
        ai_recommendation=ai_recommendation[:4000],
        generator_prompt=generator_prompt,
        notes=list(notes or [])[:20],
    )


def dump_eye_of_god_dashboard(dashboard: EyeOfGodSpyDashboard) -> dict[str, Any]:
    return dashboard.model_dump(mode="json")
