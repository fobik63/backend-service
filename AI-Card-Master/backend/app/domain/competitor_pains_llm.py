"""LLM analysis of competitor negative reviews → 3 pains + infographic offers."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.competitor_reviews_collection import MAX_COMPLAINT_TEXTS

MAIN_PAINS_COUNT = 3
MAX_PAIN_TITLE_LENGTH = 160
MAX_PAIN_SUMMARY_LENGTH = 500
MAX_OFFER_TEXT_LENGTH = 220
MAX_EVIDENCE_QUOTES = 5
MAX_EVIDENCE_QUOTE_LENGTH = 280
MAX_PRODUCT_CONTEXT_LENGTH = 1000

COMPETITOR_PAINS_SYSTEM_PROMPT = (
    "Ты аналитик маркетплейсов. Проанализируй негативные отзывы на товары "
    "конкурентов. Выдели 3 главные боли покупателей. Напиши конкретные тексты "
    "для инфографики (офферы), которые закроют эти боли на НАШЕЙ карточке."
)

COMPETITOR_PAINS_JSON_SCHEMA_HINT = (
    '{"pains":[{"rank":1,"title":"...","summary":"...","evidence_quotes":["..."]}],'
    '"recommendations":[{"pain_rank":1,"offer_text":"..."}]}'
)


class CompetitorPainsLlmProvider(StrEnum):
    """Upstream for competitor-pains analysis."""

    OPENAI = "openai"
    OLLAMA = "ollama"


class CompetitorPainsError(Exception):
    """Base competitor-pains LLM failure."""


class CompetitorPainsConfigurationError(CompetitorPainsError):
    """Missing credentials or misconfigured local/OpenAI node."""


class CompetitorPainsValidationError(CompetitorPainsError, ValueError):
    """Invalid client input."""


class CompetitorPainsUpstreamError(CompetitorPainsError):
    """LLM request failed or returned an unusable payload."""


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompetitorPainsAnalysisRequest(StrictDomainModel):
    """Flat complaint corpus from ``/competitors/reviews`` (+ optional context)."""

    complaint_texts: list[str] = Field(
        min_length=1,
        max_length=MAX_COMPLAINT_TEXTS,
        description="Negative review complaint strings collected from competitors.",
    )
    product_context: str = Field(
        default="",
        max_length=MAX_PRODUCT_CONTEXT_LENGTH,
        description="Optional brief about OUR product to tailor offers.",
    )

    @field_validator("complaint_texts", mode="before")
    @classmethod
    def _clean_complaints(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("complaint_texts must be a list of strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Each complaint must be a string.")
            text = re.sub(r"\s+", " ", item.strip())
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text[:2000])
        if not cleaned:
            raise ValueError("At least one non-empty complaint text is required.")
        return cleaned[:MAX_COMPLAINT_TEXTS]

    @field_validator("product_context", mode="before")
    @classmethod
    def _strip_context(cls, value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value.strip())
        return value


class BuyerPain(StrictDomainModel):
    """One of the three main buyer pains extracted from competitor reviews."""

    rank: int = Field(ge=1, le=MAIN_PAINS_COUNT)
    title: str = Field(min_length=1, max_length=MAX_PAIN_TITLE_LENGTH)
    summary: str = Field(min_length=1, max_length=MAX_PAIN_SUMMARY_LENGTH)
    evidence_quotes: list[str] = Field(
        default_factory=list,
        max_length=MAX_EVIDENCE_QUOTES,
    )

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value.strip())
        return value

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _clean_quotes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("evidence_quotes must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("evidence_quotes items must be strings.")
            text = re.sub(r"\s+", " ", item.strip())
            if text:
                cleaned.append(text[:MAX_EVIDENCE_QUOTE_LENGTH])
        return cleaned[:MAX_EVIDENCE_QUOTES]


class InfographicOfferRecommendation(StrictDomainModel):
    """Concrete infographic offer text that closes a mapped buyer pain."""

    pain_rank: int = Field(ge=1, le=MAIN_PAINS_COUNT)
    offer_text: str = Field(min_length=1, max_length=MAX_OFFER_TEXT_LENGTH)

    @field_validator("offer_text", mode="before")
    @classmethod
    def _strip_offer(cls, value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value.strip())
        return value


class CompetitorPainsAnalysisResult(StrictDomainModel):
    """Structured LLM output: 3 pains + matching infographic offers."""

    pains: list[BuyerPain] = Field(
        min_length=MAIN_PAINS_COUNT,
        max_length=MAIN_PAINS_COUNT,
    )
    recommendations: list[InfographicOfferRecommendation] = Field(
        min_length=MAIN_PAINS_COUNT,
        max_length=MAIN_PAINS_COUNT,
    )
    provider: CompetitorPainsLlmProvider
    model_name: str = Field(min_length=1, max_length=128)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_ranks(self) -> CompetitorPainsAnalysisResult:
        pain_ranks = sorted(p.rank for p in self.pains)
        if pain_ranks != list(range(1, MAIN_PAINS_COUNT + 1)):
            raise ValueError("pains must have unique ranks 1..3.")
        rec_ranks = sorted(r.pain_rank for r in self.recommendations)
        if rec_ranks != list(range(1, MAIN_PAINS_COUNT + 1)):
            raise ValueError("recommendations must map uniquely to pain ranks 1..3.")
        return self


def competitor_pains_system_prompt() -> str:
    """System prompt plus JSON-only contract."""

    return (
        f"{COMPETITOR_PAINS_SYSTEM_PROMPT} "
        "Не выдумывай боли, которых нет во входных отзывах. "
        "Офферы пиши коротко, конкретно, на русском — готовые тексты для плашек "
        "на нашей карточке. "
        "Отвечай ТОЛЬКО валидным JSON без markdown."
    )


def build_competitor_pains_user_prompt(request: CompetitorPainsAnalysisRequest) -> str:
    """User message with fenced complaint corpus + expected JSON shape."""

    numbered = "\n".join(
        f"{idx}. {text}" for idx, text in enumerate(request.complaint_texts, start=1)
    )
    context_block = ""
    if request.product_context.strip():
        context_block = (
            f"\nКонтекст НАШЕГО товара (учитывай при офферах):\n"
            f"{request.product_context.strip()}\n"
        )
    return (
        "Ниже негативные отзывы / жалобы покупателей на товары конкурентов.\n"
        f"{context_block}"
        "Выдели ровно 3 главные боли и по одному конкретному офферу на инфографику "
        "для каждой боли на НАШЕЙ карточке.\n"
        f"Верни строго JSON вида: {COMPETITOR_PAINS_JSON_SCHEMA_HINT}\n"
        "Правила: rank/pain_rank = 1,2,3; title — краткая формулировка боли; "
        "summary — 1–2 предложения; evidence_quotes — короткие цитаты из отзывов "
        "(если есть); offer_text — готовый текст плашки/оффера.\n"
        f"Отзывы:\n{numbered}"
    )


def normalize_competitor_pains_payload(
    payload: dict[str, Any],
    *,
    provider: CompetitorPainsLlmProvider,
    model_name: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> CompetitorPainsAnalysisResult:
    """Coerce common LLM JSON variants into the strict domain result."""

    raw = dict(payload)

    pains_src = raw.get("pains")
    if not isinstance(pains_src, list):
        for key in ("main_pains", "buyer_pains"):
            candidate = raw.get(key)
            if isinstance(candidate, list):
                pains_src = candidate
                break

    recs_src = raw.get("recommendations")
    if not isinstance(recs_src, list):
        for key in ("offers", "infographic_offers"):
            candidate = raw.get(key)
            if isinstance(candidate, list):
                recs_src = candidate
                break

    data: dict[str, Any] = {
        "pains": _coerce_pain_list(pains_src if isinstance(pains_src, list) else []),
        "recommendations": _coerce_recommendation_list(
            recs_src if isinstance(recs_src, list) else []
        ),
        "provider": provider,
        "model_name": model_name,
        "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
    }
    return CompetitorPainsAnalysisResult.model_validate(data)


def _coerce_pain_list(raw: list[Any]) -> list[dict[str, Any]]:
    pains: list[dict[str, Any]] = []
    for idx, item in enumerate(raw[:MAIN_PAINS_COUNT], start=1):
        if isinstance(item, str):
            title = item.strip()
            if not title:
                continue
            pains.append(
                {
                    "rank": idx,
                    "title": title[:MAX_PAIN_TITLE_LENGTH],
                    "summary": title[:MAX_PAIN_SUMMARY_LENGTH],
                    "evidence_quotes": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        title = str(
            item.get("title")
            or item.get("pain")
            or item.get("name")
            or item.get("problem")
            or ""
        ).strip()
        summary = str(
            item.get("summary") or item.get("description") or title
        ).strip()
        if not title:
            continue
        rank_raw = item.get("rank", idx)
        try:
            rank = int(rank_raw)
        except (TypeError, ValueError):
            rank = idx
        quotes = item.get("evidence_quotes") or item.get("evidence") or []
        if not isinstance(quotes, list):
            quotes = []
        pains.append(
            {
                "rank": rank if 1 <= rank <= MAIN_PAINS_COUNT else idx,
                "title": title[:MAX_PAIN_TITLE_LENGTH],
                "summary": (summary or title)[:MAX_PAIN_SUMMARY_LENGTH],
                "evidence_quotes": [
                    str(q).strip()[:MAX_EVIDENCE_QUOTE_LENGTH]
                    for q in quotes
                    if isinstance(q, (str, int)) and str(q).strip()
                ][:MAX_EVIDENCE_QUOTES],
            }
        )
    # Re-number if model omitted / duplicated ranks.
    if len(pains) == MAIN_PAINS_COUNT:
        for idx, pain in enumerate(pains, start=1):
            pain["rank"] = idx
    return pains


def _coerce_recommendation_list(raw: list[Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    for idx, item in enumerate(raw[:MAIN_PAINS_COUNT], start=1):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            recs.append(
                {
                    "pain_rank": idx,
                    "offer_text": text[:MAX_OFFER_TEXT_LENGTH],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        offer = str(
            item.get("offer_text")
            or item.get("offer")
            or item.get("text")
            or item.get("infographic_text")
            or ""
        ).strip()
        if not offer:
            continue
        rank_raw = item.get("pain_rank", item.get("rank", idx))
        try:
            rank = int(rank_raw)
        except (TypeError, ValueError):
            rank = idx
        recs.append(
            {
                "pain_rank": rank if 1 <= rank <= MAIN_PAINS_COUNT else idx,
                "offer_text": offer[:MAX_OFFER_TEXT_LENGTH],
            }
        )
    if len(recs) == MAIN_PAINS_COUNT:
        for idx, rec in enumerate(recs, start=1):
            rec["pain_rank"] = idx
    return recs
