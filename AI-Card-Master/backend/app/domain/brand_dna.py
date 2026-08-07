"""BrandDNA — learned visual identity from a seller's successful generations (plan §58).

Pipeline:
1. Collect completed generation slides (styles + prompts) for the seller.
2. Aggregate recurring palette / lighting / typography / composition signals.
3. Persist Midjourney + Claude context strings on ``brand_dnas``.
4. Auto-inject that context into every new image and copy prompt.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-_/]{2,}")
_NOISE_TOKENS = frozenset(
    {
        "the",
        "and",
        "with",
        "for",
        "from",
        "style",
        "product",
        "card",
        "image",
        "photo",
        "slide",
        "background",
        "товар",
        "карточка",
        "стиль",
        "фон",
        "lora",
        "brand",
        "brnd",
    }
)
_MJ_INJECTION_TAG = "[BrandDNA]"
_CLAUDE_INJECTION_TAG = "[BrandDNA Context]"


class BrandDNAStatus(StrEnum):
    """Lifecycle of a seller BrandDNA profile."""

    EMPTY = "empty"
    READY = "ready"
    STALE = "stale"
    ANALYZING = "analyzing"


@dataclass(frozen=True, slots=True)
class SuccessfulGenerationSample:
    """One completed generation used as a BrandDNA learning signal."""

    job_id: UUID
    product_category: str | None
    selected_styles: tuple[str, ...]
    prompts: tuple[str, ...]
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BrandDNASignals:
    """Aggregated visual identity extracted from successful cards."""

    dominant_styles: tuple[str, ...]
    palette_keywords: tuple[str, ...]
    lighting_mood: tuple[str, ...]
    composition_keywords: tuple[str, ...]
    category_hints: tuple[str, ...]
    sample_count: int
    source_job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class BrandDNAContext:
    """Active BrandDNA snippet injected into Midjourney / Claude prompts."""

    id: UUID
    user_id: UUID
    midjourney_context: str
    claude_context: str
    dominant_styles: tuple[str, ...]
    sample_count: int


@dataclass(frozen=True, slots=True)
class BrandDNAView:
    """Full projection of a persisted BrandDNA row."""

    id: UUID
    user_id: UUID
    status: BrandDNAStatus
    is_active: bool
    midjourney_context: str | None
    claude_context: str | None
    dominant_styles: tuple[str, ...]
    palette_keywords: tuple[str, ...]
    lighting_mood: tuple[str, ...]
    composition_keywords: tuple[str, ...]
    category_hints: tuple[str, ...]
    sample_count: int
    source_job_ids: tuple[UUID, ...]
    version: int
    last_analyzed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def analyze_successful_generations(
    samples: tuple[SuccessfulGenerationSample, ...],
    *,
    max_styles: int = 5,
    max_keywords: int = 12,
) -> BrandDNASignals | None:
    """Derive BrandDNA signals from completed seller generations.

    Returns ``None`` when there is not enough successful material to learn from.
    """

    if not samples:
        return None

    style_counter: Counter[str] = Counter()
    token_counter: Counter[str] = Counter()
    lighting_counter: Counter[str] = Counter()
    composition_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    source_ids: list[UUID] = []

    for sample in samples:
        source_ids.append(sample.job_id)
        if sample.product_category and sample.product_category.strip():
            category_counter[sample.product_category.strip().lower()] += 1
        for style in sample.selected_styles:
            cleaned = " ".join(style.strip().split())
            if cleaned:
                style_counter[cleaned[:200]] += 1
                _accumulate_tokens(token_counter, lighting_counter, composition_counter, cleaned)
        for prompt in sample.prompts:
            cleaned = " ".join(prompt.strip().split())
            if cleaned:
                _accumulate_tokens(token_counter, lighting_counter, composition_counter, cleaned)

    if not style_counter and not token_counter:
        return None

    palette = _pick_tokens(
        token_counter,
        max_keywords,
        prefer=("color", "palette", "tone", "hue", "цвет", "палитр", "beige", "gold", "navy"),
    )
    lighting = _pick_tokens(
        lighting_counter,
        max_keywords // 2 or 1,
        prefer=("light", "lighting", "golden", "soft", "studio", "свет", "освещ"),
    )
    composition = _pick_tokens(
        composition_counter,
        max_keywords // 2 or 1,
        prefer=("composition", "layout", "infographic", "minimal", "композ", "инфограф"),
    )
    if not palette:
        palette = tuple(token for token, _ in token_counter.most_common(max_keywords))
    dominant = tuple(style for style, _ in style_counter.most_common(max_styles))
    categories = tuple(cat for cat, _ in category_counter.most_common(5))

    return BrandDNASignals(
        dominant_styles=dominant,
        palette_keywords=palette,
        lighting_mood=lighting,
        composition_keywords=composition,
        category_hints=categories,
        sample_count=len(samples),
        source_job_ids=tuple(dict.fromkeys(source_ids)),
    )


def build_midjourney_context(signals: BrandDNASignals) -> str:
    """Build a compact Midjourney/SD style suffix from BrandDNA signals."""

    parts: list[str] = ["consistent seller brand identity"]
    if signals.dominant_styles:
        parts.append(f"recurring styles: {', '.join(signals.dominant_styles[:3])}")
    if signals.palette_keywords:
        parts.append(f"brand palette: {', '.join(signals.palette_keywords[:8])}")
    if signals.lighting_mood:
        parts.append(f"lighting mood: {', '.join(signals.lighting_mood[:5])}")
    if signals.composition_keywords:
        parts.append(f"composition: {', '.join(signals.composition_keywords[:5])}")
    parts.append("match previous successful marketplace cards of this seller")
    parts.append("no competing visual languages")
    return ", ".join(parts)[:1500]


def build_claude_context(signals: BrandDNASignals) -> str:
    """Build Claude copywriting/vision guidance from BrandDNA signals."""

    lines = [
        "Preserve brand visual and verbal unity across all marketplace cards.",
        f"Learned from {signals.sample_count} successful generation(s).",
    ]
    if signals.dominant_styles:
        lines.append(f"Dominant visual styles: {', '.join(signals.dominant_styles[:5])}.")
    if signals.palette_keywords:
        lines.append(f"Brand palette cues: {', '.join(signals.palette_keywords[:10])}.")
    if signals.lighting_mood:
        lines.append(f"Preferred lighting: {', '.join(signals.lighting_mood[:6])}.")
    if signals.composition_keywords:
        lines.append(
            f"Composition patterns: {', '.join(signals.composition_keywords[:6])}."
        )
    if signals.category_hints:
        lines.append(f"Frequent categories: {', '.join(signals.category_hints[:5])}.")
    lines.append(
        "Keep tone, structure, and aesthetic consistent with the seller's proven winners."
    )
    return " ".join(lines)[:2500]


def apply_brand_dna_to_style(selected_style: str, dna: BrandDNAContext) -> str:
    """Append BrandDNA style cues to a Midjourney/SD style descriptor."""

    base = selected_style.strip()
    ctx = dna.midjourney_context.strip()
    if not ctx:
        return base
    marker = ctx[:48]
    if marker and marker in base:
        return base
    if dna.dominant_styles:
        top = dna.dominant_styles[0]
        if top and top in base and marker in base:
            return base
    merged = f"{base}, {ctx}" if base else ctx
    return merged[:500]


def apply_brand_dna_to_prompt(prompt: str, dna: BrandDNAContext) -> str:
    """Inject BrandDNA into a Midjourney/SD generation user prompt."""

    base = prompt.strip()
    ctx = dna.midjourney_context.strip()
    if not ctx:
        return base
    injection = f"{_MJ_INJECTION_TAG} {ctx}".strip()
    if injection in base or _MJ_INJECTION_TAG in base:
        return base
    merged = f"{base}\n{injection}".strip() if base else injection
    return merged[:4000]


def apply_brand_dna_to_claude_system(system_prompt: str, dna: BrandDNAContext) -> str:
    """Append BrandDNA guidance to a Claude system prompt."""

    return mix_claude_system_prompt(system_prompt, dna.claude_context)


def apply_brand_dna_to_claude_user(user_prompt: str, dna: BrandDNAContext) -> str:
    """Append BrandDNA context to a Claude user prompt (marketplace copy path)."""

    return mix_claude_user_prompt(user_prompt, dna.claude_context)


def mix_claude_system_prompt(system_prompt: str, claude_context: str | None) -> str:
    """Append raw BrandDNA Claude context to a system prompt."""

    base = system_prompt.strip()
    ctx = (claude_context or "").strip()
    if not ctx:
        return base
    block = f"{_CLAUDE_INJECTION_TAG}\n{ctx}"
    if _CLAUDE_INJECTION_TAG in base or ctx[:80] in base:
        return base
    return f"{base}\n\n{block}".strip()


def mix_claude_user_prompt(user_prompt: str, claude_context: str | None) -> str:
    """Append raw BrandDNA Claude context to a user prompt."""

    base = user_prompt.strip()
    ctx = (claude_context or "").strip()
    if not ctx:
        return base
    block = f"{_CLAUDE_INJECTION_TAG}: {ctx}"
    if _CLAUDE_INJECTION_TAG in base:
        return base
    return f"{base}\n\n{block}".strip()[:12_000]


def context_from_view(view: BrandDNAView) -> BrandDNAContext | None:
    """Project a ready BrandDNA row into an injectable context."""

    if not view.is_active:
        return None
    if view.status not in {BrandDNAStatus.READY, BrandDNAStatus.STALE}:
        return None
    mj = (view.midjourney_context or "").strip()
    claude = (view.claude_context or "").strip()
    if not mj and not claude:
        return None
    return BrandDNAContext(
        id=view.id,
        user_id=view.user_id,
        midjourney_context=mj,
        claude_context=claude or mj,
        dominant_styles=view.dominant_styles,
        sample_count=view.sample_count,
    )


def _accumulate_tokens(
    token_counter: Counter[str],
    lighting_counter: Counter[str],
    composition_counter: Counter[str],
    text: str,
) -> None:
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("-_/")
        if len(token) < 3 or token in _NOISE_TOKENS:
            continue
        if token.startswith("brnd"):
            continue
        token_counter[token] += 1
        if any(
            key in token
            for key in ("light", "glow", "shadow", "golden", "studio", "свет", "освещ")
        ):
            lighting_counter[token] += 1
        if any(
            key in token
            for key in (
                "compos",
                "layout",
                "grid",
                "minimal",
                "infograph",
                "композ",
                "инфограф",
            )
        ):
            composition_counter[token] += 1


def _pick_tokens(
    counter: Counter[str],
    limit: int,
    *,
    prefer: tuple[str, ...],
) -> tuple[str, ...]:
    if limit <= 0 or not counter:
        return ()
    preferred = [
        token
        for token, _ in counter.most_common()
        if any(hint in token for hint in prefer)
    ]
    rest = [token for token, _ in counter.most_common() if token not in preferred]
    merged = preferred + rest
    return tuple(merged[:limit])
