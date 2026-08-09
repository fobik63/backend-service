"""Semantic Filtering (Delta) — compress competitor context for Claude (plan §69).

Instead of feeding the full competitor dump on every call, extract only key
changes vs a prior snapshot (or a baseline-compressed view) and render a short
prompt payload. Deterministic: no LLM spend.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.competitor_audit import (
    CompetitorCardScrapeResult,
    CompetitorReview,
)

# Aggressive caps for Claude prompts after Semantic Filtering (vs full dump).
DELTA_MAX_NEW_REVIEWS = 12
DELTA_MAX_CHANGED_SPECS = 20
DELTA_MAX_DESCRIPTION_CHARS = 1200
DELTA_MAX_REVIEW_CHARS = 400
BASELINE_MAX_REVIEWS_PER_BUCKET = 10
BASELINE_MAX_SPECS = 25
BASELINE_MAX_DESCRIPTION_CHARS = 1800


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for semantic-filter payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DeltaChangeKind(StrEnum):
    """What changed between two competitor card snapshots."""

    TITLE = "title"
    PRICE = "price"
    DESCRIPTION = "description"
    SPECS = "specs"
    REVIEW_NEW = "review_new"
    REVIEW_REMOVED = "review_removed"
    PHOTOS = "photos"
    FIRST_SEEN = "first_seen"


class ContextDeltaItem(StrictDomainModel):
    """One compressed change line for the Claude prompt."""

    kind: DeltaChangeKind
    summary: str = Field(min_length=1, max_length=800)
    before: str | None = Field(default=None, max_length=500)
    after: str | None = Field(default=None, max_length=500)

    @field_validator("summary", mode="before")
    @classmethod
    def _strip_summary(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("before", "after", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return value

    @field_validator("summary", mode="after")
    @classmethod
    def _require_summary(cls, value: str) -> str:
        if not value:
            raise ValueError("summary must not be empty.")
        return value[:800]


class CompetitorContextDelta(StrictDomainModel):
    """Compressed competitor context ready for Claude (plan §69 Semantic Filtering)."""

    article: str = Field(min_length=1, max_length=64)
    marketplace: str = Field(min_length=1, max_length=32)
    title: str | None = Field(default=None, max_length=500)
    is_first_seen: bool = False
    has_meaningful_changes: bool = True
    compression_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    estimated_tokens_before: int = Field(default=0, ge=0)
    estimated_tokens_after: int = Field(default=0, ge=0)
    stable_identity: str = Field(
        default="",
        max_length=200,
        description="Unchanged identity line (article, marketplace, title).",
    )
    price_before_rub: str | None = Field(default=None, max_length=32)
    price_after_rub: str | None = Field(default=None, max_length=32)
    description_excerpt: str = Field(default="", max_length=DELTA_MAX_DESCRIPTION_CHARS)
    changed_specs: list[str] = Field(default_factory=list, max_length=DELTA_MAX_CHANGED_SPECS)
    new_reviews_low: list[str] = Field(default_factory=list, max_length=DELTA_MAX_NEW_REVIEWS)
    new_reviews_high: list[str] = Field(default_factory=list, max_length=DELTA_MAX_NEW_REVIEWS)
    changes: list[ContextDeltaItem] = Field(default_factory=list, max_length=80)
    notes: list[str] = Field(default_factory=list, max_length=20)


class CompetitorCardSnapshot(StrictDomainModel):
    """Lightweight prior scrape fingerprint stored in Redis for Delta computation."""

    marketplace: str = Field(min_length=1, max_length=32)
    article: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    description_sha256: str = Field(default="", max_length=64)
    description_excerpt: str = Field(default="", max_length=BASELINE_MAX_DESCRIPTION_CHARS)
    price_before_discount_kopecks: int | None = Field(default=None, ge=0)
    price_after_discount_kopecks: int | None = Field(default=None, ge=0)
    specs_fingerprint: str = Field(default="", max_length=64)
    specs: list[str] = Field(default_factory=list, max_length=200)
    review_fingerprints: list[str] = Field(default_factory=list, max_length=100)
    photo_count: int = Field(default=0, ge=0, le=100)
    photo_urls_fingerprint: str = Field(default="", max_length=64)


def estimate_text_tokens(text: str) -> int:
    """Cheap UTF-8 heuristic (~4 chars/token). Good enough for budget gates."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_card_prompt_tokens(card: CompetitorCardScrapeResult) -> int:
    """Estimate tokens if the full competitor card were dumped into a prompt."""

    parts: list[str] = [
        card.title or "",
        card.description or "",
        card.article,
        card.marketplace.value,
    ]
    for row in card.specs:
        parts.append(f"{row.name}:{row.value}")
    for review in (*card.reviews_low, *card.reviews_high):
        parts.append(review.text or "")
        parts.append(review.pros or "")
        parts.append(review.cons or "")
    return estimate_text_tokens("\n".join(parts))


def fingerprint_text(value: str) -> str:
    """Stable SHA-256 hex for review / description / URL set identity."""

    normalized = re.sub(r"\s+", " ", (value or "").strip().casefold())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_card_snapshot(card: CompetitorCardScrapeResult) -> CompetitorCardSnapshot:
    """Persistable fingerprint of a scraped competitor card."""

    specs_lines = [f"{row.name.strip()}: {row.value.strip()}" for row in card.specs]
    review_fps: list[str] = []
    for review in (*card.reviews_low, *card.reviews_high):
        review_fps.append(_review_fingerprint(review))
    photo_blob = "\n".join(u.strip() for u in card.photo_urls if u.strip())
    desc = (card.description or "").strip()
    return CompetitorCardSnapshot(
        marketplace=card.marketplace.value,
        article=card.article,
        title=card.title,
        description_sha256=fingerprint_text(desc) if desc else "",
        description_excerpt=_excerpt(desc, BASELINE_MAX_DESCRIPTION_CHARS),
        price_before_discount_kopecks=card.price_before_discount_kopecks,
        price_after_discount_kopecks=card.price_after_discount_kopecks,
        specs_fingerprint=fingerprint_text("\n".join(specs_lines)),
        specs=specs_lines[:200],
        review_fingerprints=review_fps[:100],
        photo_count=len([u for u in card.photo_urls if u.strip()]),
        photo_urls_fingerprint=fingerprint_text(photo_blob) if photo_blob else "",
    )


def snapshot_to_dict(snapshot: CompetitorCardSnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")


def snapshot_from_dict(payload: dict[str, Any] | None) -> CompetitorCardSnapshot | None:
    if not payload:
        return None
    try:
        return CompetitorCardSnapshot.model_validate(payload)
    except Exception:
        return None


def redis_competitor_snapshot_key(*, marketplace: str, article: str) -> str:
    """Content key for prior-card snapshots used by Semantic Filtering."""

    mp = marketplace.strip().lower() or "unknown"
    art = article.strip().lower() or "unknown"
    return f"competitor:snapshot:v1:{mp}:{art}"


def compute_competitor_context_delta(
    current: CompetitorCardScrapeResult,
    previous: CompetitorCardSnapshot | None = None,
) -> CompetitorContextDelta:
    """Extract key changes (Delta) or a baseline-compressed first-seen view."""

    tokens_before = estimate_card_prompt_tokens(current)
    title = (current.title or current.article).strip()
    price_before = _kopecks_to_rub(current.price_before_discount_kopecks)
    price_after = _kopecks_to_rub(current.price_after_discount_kopecks)
    identity = (
        f"article={current.article}; marketplace={current.marketplace.value}; "
        f"title={title}"
    )

    if previous is None:
        return _baseline_compress(
            current,
            tokens_before=tokens_before,
            identity=identity,
            price_before=price_before,
            price_after=price_after,
        )

    changes: list[ContextDeltaItem] = []
    notes: list[str] = []

    if (previous.title or "").strip() != (current.title or "").strip():
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.TITLE,
                summary="Title changed",
                before=(previous.title or "")[:500] or None,
                after=(current.title or "")[:500] or None,
            )
        )

    if (
        previous.price_before_discount_kopecks != current.price_before_discount_kopecks
        or previous.price_after_discount_kopecks != current.price_after_discount_kopecks
    ):
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.PRICE,
                summary="Price changed",
                before=(
                    f"before={_kopecks_to_rub(previous.price_before_discount_kopecks)};"
                    f" after={_kopecks_to_rub(previous.price_after_discount_kopecks)}"
                ),
                after=f"before={price_before}; after={price_after}",
            )
        )

    desc = (current.description or "").strip()
    desc_fp = fingerprint_text(desc) if desc else ""
    description_excerpt = ""
    if desc_fp != (previous.description_sha256 or ""):
        description_excerpt = _excerpt(desc, DELTA_MAX_DESCRIPTION_CHARS)
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.DESCRIPTION,
                summary="Description changed — excerpt only",
                after=description_excerpt[:500] or None,
            )
        )
    else:
        notes.append("description_unchanged")
        description_excerpt = _excerpt(
            previous.description_excerpt or desc,
            min(400, DELTA_MAX_DESCRIPTION_CHARS),
        )

    current_specs = {
        f"{row.name.strip()}: {row.value.strip()}" for row in current.specs
    }
    prev_specs = set(previous.specs)
    added_specs = sorted(current_specs - prev_specs)
    removed_specs = sorted(prev_specs - current_specs)
    changed_specs: list[str] = []
    for line in added_specs[:DELTA_MAX_CHANGED_SPECS]:
        changed_specs.append(f"+ {line}"[:500])
    remaining = DELTA_MAX_CHANGED_SPECS - len(changed_specs)
    for line in removed_specs[: max(0, remaining)]:
        changed_specs.append(f"- {line}"[:500])
    if added_specs or removed_specs:
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.SPECS,
                summary=(
                    f"Specs delta: +{len(added_specs)} / -{len(removed_specs)}"
                ),
            )
        )
    else:
        notes.append("specs_unchanged")

    prev_reviews = set(previous.review_fingerprints)
    new_low = _new_review_texts(current.reviews_low, prev_reviews)
    new_high = _new_review_texts(current.reviews_high, prev_reviews)
    removed_count = len(prev_reviews - {_review_fingerprint(r) for r in (*current.reviews_low, *current.reviews_high)})
    if new_low or new_high:
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.REVIEW_NEW,
                summary=(
                    f"New reviews: low={len(new_low)} high={len(new_high)}"
                ),
            )
        )
    else:
        notes.append("reviews_unchanged")
    if removed_count:
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.REVIEW_REMOVED,
                summary=f"Removed/expired review fingerprints: {removed_count}",
            )
        )

    photo_blob = "\n".join(u.strip() for u in current.photo_urls if u.strip())
    photo_fp = fingerprint_text(photo_blob) if photo_blob else ""
    if photo_fp != (previous.photo_urls_fingerprint or ""):
        changes.append(
            ContextDeltaItem(
                kind=DeltaChangeKind.PHOTOS,
                summary=(
                    f"Gallery changed: was={previous.photo_count} "
                    f"now={len([u for u in current.photo_urls if u.strip()])}"
                ),
            )
        )
    else:
        notes.append("photos_unchanged")

    has_changes = bool(changes)
    if not has_changes:
        notes.append("no_textual_delta_use_minimal_identity")

    delta = CompetitorContextDelta(
        article=current.article,
        marketplace=current.marketplace.value,
        title=current.title,
        is_first_seen=False,
        has_meaningful_changes=has_changes,
        stable_identity=identity,
        price_before_rub=price_before,
        price_after_rub=price_after,
        description_excerpt=description_excerpt,
        changed_specs=changed_specs[:DELTA_MAX_CHANGED_SPECS],
        new_reviews_low=new_low[:DELTA_MAX_NEW_REVIEWS],
        new_reviews_high=new_high[:DELTA_MAX_NEW_REVIEWS],
        changes=changes[:80],
        notes=notes[:20],
        estimated_tokens_before=tokens_before,
        estimated_tokens_after=0,
        compression_ratio=1.0,
    )
    after = estimate_text_tokens(render_competitor_delta_prompt_body(delta))
    return delta.model_copy(
        update={
            "estimated_tokens_after": after,
            "compression_ratio": (
                round(after / tokens_before, 4) if tokens_before else 1.0
            ),
        }
    )


def render_competitor_delta_prompt_body(delta: CompetitorContextDelta) -> str:
    """Render compressed Delta block (without the outer audit instruction wrapper)."""

    lines: list[str] = [
        "SEMANTIC_FILTER_DELTA (compressed competitor context — key changes only)",
        delta.stable_identity,
        f"is_first_seen={delta.is_first_seen}",
        f"has_meaningful_changes={delta.has_meaningful_changes}",
        f"price_before_rub={delta.price_before_rub or 'n/a'}",
        f"price_after_rub={delta.price_after_rub or 'n/a'}",
    ]
    if delta.changes:
        lines.append("changes:")
        for item in delta.changes:
            piece = f"- [{item.kind.value}] {item.summary}"
            if item.before:
                piece += f" | before={item.before}"
            if item.after:
                piece += f" | after={item.after}"
            lines.append(piece)
    if delta.description_excerpt:
        lines.append(f"description_excerpt:\n{delta.description_excerpt}")
    if delta.changed_specs:
        lines.append("specs_delta:\n" + "\n".join(delta.changed_specs))
    elif not delta.is_first_seen:
        lines.append("specs_delta: (unchanged)")
    lines.append(
        f"new_reviews_low ({len(delta.new_reviews_low)}):\n"
        + (
            "\n---\n".join(delta.new_reviews_low)
            if delta.new_reviews_low
            else "(none)"
        )
    )
    lines.append(
        f"new_reviews_high ({len(delta.new_reviews_high)}):\n"
        + (
            "\n---\n".join(delta.new_reviews_high)
            if delta.new_reviews_high
            else "(none)"
        )
    )
    if delta.notes:
        lines.append("notes: " + "; ".join(delta.notes))
    return "\n".join(lines)


def build_competitor_delta_analysis_prompt(
    *,
    delta: CompetitorContextDelta,
    image_count: int,
) -> str:
    """User prompt for Claude when Semantic Filtering is active."""

    return (
        "Аудит карточки конкурента (режим Semantic Filtering / Delta).\n"
        f"images_attached={image_count} (первое = главный слайд)\n"
        f"{render_competitor_delta_prompt_body(delta)}\n"
        "Используй ТОЛЬКО переданные изменения и excerpt. "
        "Не выдумывай отзывы/характеристики, которых нет в Delta. "
        "Если has_meaningful_changes=false — опирайся на Vision-фото и "
        "минимальный identity-контекст.\n"
        "Поле article в ответе должно быть ровно: "
        f"{delta.article}. "
        "Поле marketplace: "
        f"{delta.marketplace}. "
        "Сначала reasoning_trace, затем заполняй JSON."
    )


def _baseline_compress(
    current: CompetitorCardScrapeResult,
    *,
    tokens_before: int,
    identity: str,
    price_before: str,
    price_after: str,
) -> CompetitorContextDelta:
    """First-seen path: still compress aggressively (dedupe + caps)."""

    desc = _excerpt((current.description or "").strip(), BASELINE_MAX_DESCRIPTION_CHARS)
    specs = [
        f"{row.name.strip()}: {row.value.strip()}"
        for row in current.specs[:BASELINE_MAX_SPECS]
    ]
    low = _dedupe_review_texts(current.reviews_low)[:BASELINE_MAX_REVIEWS_PER_BUCKET]
    high = _dedupe_review_texts(current.reviews_high)[:BASELINE_MAX_REVIEWS_PER_BUCKET]
    changes = [
        ContextDeltaItem(
            kind=DeltaChangeKind.FIRST_SEEN,
            summary=(
                "First snapshot — baseline compression "
                f"(reviews_low={len(low)}, reviews_high={len(high)}, "
                f"specs={len(specs)})"
            ),
        )
    ]
    delta = CompetitorContextDelta(
        article=current.article,
        marketplace=current.marketplace.value,
        title=current.title,
        is_first_seen=True,
        has_meaningful_changes=True,
        stable_identity=identity,
        price_before_rub=price_before,
        price_after_rub=price_after,
        description_excerpt=desc[:DELTA_MAX_DESCRIPTION_CHARS],
        changed_specs=[f"= {s}" for s in specs][:DELTA_MAX_CHANGED_SPECS],
        new_reviews_low=low[:DELTA_MAX_NEW_REVIEWS],
        new_reviews_high=high[:DELTA_MAX_NEW_REVIEWS],
        changes=changes,
        notes=["baseline_compression_no_prior_snapshot"],
        estimated_tokens_before=tokens_before,
        estimated_tokens_after=0,
        compression_ratio=1.0,
    )
    after = estimate_text_tokens(render_competitor_delta_prompt_body(delta))
    return delta.model_copy(
        update={
            "estimated_tokens_after": after,
            "compression_ratio": (
                round(after / tokens_before, 4) if tokens_before else 1.0
            ),
        }
    )


def _review_fingerprint(review: CompetitorReview) -> str:
    if review.review_id and review.review_id.strip():
        return fingerprint_text(f"id:{review.review_id.strip()}")
    blob = "|".join(
        [
            str(review.rating),
            (review.text or "").strip(),
            (review.pros or "").strip(),
            (review.cons or "").strip(),
        ]
    )
    return fingerprint_text(blob)


def _new_review_texts(
    reviews: list[CompetitorReview],
    previous_fps: set[str],
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for review in reviews:
        fp = _review_fingerprint(review)
        if fp in previous_fps or fp in seen:
            continue
        seen.add(fp)
        text = _format_review_line(review)
        if text:
            out.append(text)
        if len(out) >= DELTA_MAX_NEW_REVIEWS:
            break
    return out


def _dedupe_review_texts(reviews: list[CompetitorReview]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for review in reviews:
        fp = _review_fingerprint(review)
        if fp in seen:
            continue
        seen.add(fp)
        text = _format_review_line(review)
        if text:
            out.append(text)
    return out


def _format_review_line(review: CompetitorReview) -> str:
    parts: list[str] = [f"rating={review.rating}"]
    body = (review.text or "").strip()
    if body:
        parts.append(body[:DELTA_MAX_REVIEW_CHARS])
    if review.pros:
        parts.append(f"pros: {review.pros[:200]}")
    if review.cons:
        parts.append(f"cons: {review.cons[:200]}")
    if len(parts) <= 1:
        return ""
    return " | ".join(parts)


def _excerpt(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    if limit < 80:
        return cleaned[:limit]
    head = limit * 2 // 3
    tail = limit - head - 5
    return f"{cleaned[:head].rstrip()} ... {cleaned[-tail:].lstrip()}"


def _kopecks_to_rub(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / 100:.2f}"
