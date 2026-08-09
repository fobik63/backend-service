"""Competitor negative-review pain analysis (plan §71).

Pipeline:
1. Filter junk (user error, delivery, emotional noise) from competitor reviews.
2. Extract 3–5 real product pains.
3. Produce 4 pain→solution infographic badges + SEO title/description for WB/Ozon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PainAnalysisJobStatus(StrEnum):
    """Lifecycle of an async pain-analysis job."""

    QUEUED = "queued"
    FILTERING = "filtering"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for pain-analysis payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PainAnalysisRequest(StrictDomainModel):
    """Input for competitor negative-review analysis."""

    product_name: str = Field(min_length=1, max_length=300)
    product_specs: str = Field(default="", max_length=4000)
    platform: str = Field(min_length=1, max_length=32)
    raw_negative_reviews: list[str] = Field(min_length=1, max_length=100)

    @field_validator("product_name", "product_specs", "platform", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("platform", mode="after")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        normalized = value.casefold()
        aliases = {
            "wb": "wildberries",
            "wildberries": "wildberries",
            "вайлдберриз": "wildberries",
            "ozon": "ozon",
            "озон": "ozon",
        }
        if normalized not in aliases:
            raise ValueError("platform must be wildberries or ozon.")
        return aliases[normalized]

    @field_validator("raw_negative_reviews", mode="before")
    @classmethod
    def _clean_reviews(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("raw_negative_reviews must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Each review must be a string.")
            text = re.sub(r"\s+", " ", item.strip())
            if text:
                cleaned.append(text[:2000])
        if not cleaned:
            raise ValueError("At least one non-empty review is required.")
        return cleaned[:100]


class PainAnalysisResult(StrictDomainModel):
    """Strict JSON output matching plan §71 schema."""

    filtered_out_junk: list[str] = Field(default_factory=list, max_length=100)
    real_product_pains: list[str] = Field(min_length=1, max_length=5)
    infographic_badges: list[str] = Field(min_length=4, max_length=4)
    seo_title: str = Field(min_length=1, max_length=200)
    seo_description: str = Field(min_length=1, max_length=4000)
    model_name: str = Field(default="deterministic", min_length=1, max_length=128)
    insufficient_data: bool = False

    @field_validator(
        "filtered_out_junk",
        "real_product_pains",
        "infographic_badges",
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

    @model_validator(mode="after")
    def _validate_counts(self) -> PainAnalysisResult:
        if len(self.infographic_badges) != 4:
            raise ValueError("infographic_badges must contain exactly 4 theses.")
        if not self.insufficient_data and len(self.real_product_pains) < 1:
            raise ValueError("At least one real product pain is required.")
        return self


@dataclass(frozen=True, slots=True)
class PainAnalysisJobView:
    """Projection of a persisted pain-analysis job."""

    id: UUID
    user_id: UUID
    status: PainAnalysisJobStatus
    celery_task_id: str | None
    product_name: str
    platform: str
    request_payload: dict[str, Any]
    filter_preview: dict[str, Any] | None
    analysis_result: dict[str, Any] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


PAIN_ANALYSIS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "filtered_out_junk",
        "real_product_pains",
        "infographic_badges",
        "seo_title",
        "seo_description",
    ],
    "properties": {
        "filtered_out_junk": {
            "type": "array",
            "items": {"type": "string"},
        },
        "real_product_pains": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"type": "string"},
        },
        "infographic_badges": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string"},
        },
        "seo_title": {"type": "string"},
        "seo_description": {"type": "string"},
    },
}


_PAIN_ANALYSIS_SYSTEM_PROMPT = (
    "Ты — профессиональный продуктовый аналитик и маркетолог для маркетплейсов "
    "Wildberries / Ozon. "
    "Проанализируй массив отрицательных отзывов конкурентов, "
    "ОТФИЛЬТРУЙ нерелевантный мусор и человеческий фактор, "
    "выдели РЕАЛЬНЫЕ проблемы товара и создай на их основе закрывающий боли контент. "
    "ИГНОРИРУЙ: ошибки пользователя, претензии к доставке/складу маркетплейса, "
    "эмоциональный шум без конкретики. "
    "УЧИТЫВАЙ только конструктивные недостатки, несоответствие ожиданиям и "
    "плохую родную упаковку производителя. "
    "Не выдумывай проблемы, которых нет во входных отзывах. "
    "Если реальных болей мало — верни только подтверждённые. "
    "Return ONLY valid JSON matching the schema."
)


# Heuristic junk patterns for deterministic preview / Claude-unavailable fallback.
_USER_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"не\s+разобрал",
        r"не\s+прочитал\s+инструкц",
        r"не\s+понял\s+как",
        r"думал\s+(что\s+)?это\s+друг",
        r"ожидал\s+друг(ой|ое|ую)",
        r"не\s+тот\s+размер.*(в\s+описании|как\s+в\s+карточк)",
        r"сам\s+виноват",
        r"не\s+умею",
    )
)

_DELIVERY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"порвал(и|а)?\s+коробк",
        r"долго\s+(шло|шла|ехал|ехала|доставля)",
        r"перепутал(и|а)?\s+(цвет|товар|размер)\s+(на\s+склад|в\s+пвз|на\s+wb|на\s+ozon)",
        r"повредил(и|а)?\s+при\s+транспорт",
        r"курьер",
        r"пункт\s+выдач",
        r"пвз",
        r"логистик",
        r"упаковк[ауи].*(мят|порван|разбит).*(достав|транспорт|склад|пвз)",
        r"(мят|порван|разбит).*при\s+достав",
    )
)

_EMOTIONAL_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(ужасно|отстой|дерьмо|не\s+понравилось|верните\s+деньги)[.!\s]*$",
        r"^(плохо|ужас|кошмар|обман)[.!\s]*$",
        r"^не\s+рекомендую[.!\s]*$",
        r"^полный\s+отстой[.!\s]*$",
    )
)

_PRODUCT_PAIN_HINTS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"хлипк",
        r"сломал",
        r"треснул",
        r"скрип",
        r"шв[ыа]",
        r"батаре",
        r"аккумулятор",
        r"заряд",
        r"маломерит",
        r"великомерит",
        r"выцвет",
        r"пахнет",
        r"запах",
        r"резин",
        r"пластик",
        r"гн[её]т",
        r"не\s+держит",
        r"протека",
        r"качество",
        r"брак",
        r"рассып",
        r"комплект",
        r"инструкц.*(нет|отсутств)",
        r"софт",
        r"прошивк",
        r"экран",
        r"камер",
        r"шум",
        r"греет",
        r"перегрев",
        r"ткан",
        r"материал",
        r"размер.*(маловат|великоват|не\s+соответств)",
    )
)


def pain_analysis_system_prompt() -> str:
    return _PAIN_ANALYSIS_SYSTEM_PROMPT


def build_pain_analysis_prompt(*, request: PainAnalysisRequest) -> str:
    """User prompt with product context and raw competitor negatives."""

    reviews_block = "\n".join(
        f"{idx}. {text}" for idx, text in enumerate(request.raw_negative_reviews, start=1)
    )
    platform_label = (
        "Wildberries" if request.platform == "wildberries" else "Ozon"
    )
    specs = request.product_specs.strip() or "не указаны"
    return (
        "ВХОДНЫЕ ДАННЫЕ:\n"
        f"- Товар: {request.product_name}\n"
        f"- Характеристики: {specs}\n"
        f"- Маркетплейс: {platform_label}\n"
        "- Необработанные отрицательные отзывы конкурентов:\n"
        f"{reviews_block}\n\n"
        "КРИТЕРИИ ФИЛЬТРАЦИИ ОТЗЫВОВ (ОБЯЗАТЕЛЬНО):\n"
        "❌ ИГНОРИРОВАТЬ: ошибки пользователя; претензии к доставке/службе маркетплейса; "
        "эмоциональный шум без конкретики.\n"
        "✅ УЧИТЫВАТЬ: конструктивные недостатки; несоответствие ожиданиям; "
        "плохую родную упаковку производителя.\n\n"
        "ИНСТРУКЦИЯ:\n"
        "1. Выдели 3-5 НАСТОЯЩИХ болей товара из отфильтрованных данных.\n"
        "2. Сформулируй ровно 4 тезиса для инфографики (плашек), показывающих, "
        "что НАШ товар лишён этих дефектов (Боль → Решение).\n"
        f"3. Напиши SEO-оптимизированные seo_title и seo_description для {platform_label}, "
        "естественно закрывающие эти боли.\n"
        "В filtered_out_junk укажи отсеянный отзыв и краткую причину.\n"
        "Верни строго JSON по схеме."
    )


def redis_pain_analysis_key(job_id: UUID, stage: str) -> str:
    return f"pain_analysis:{job_id}:{stage}"


def dump_pain_analysis_result(result: PainAnalysisResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def _classify_junk(review: str) -> str | None:
    """Return junk reason or None if the review may describe a real product issue."""

    text = review.strip()
    if len(text) < 8:
        return "эмоциональный шум без конкретики"
    for pattern in _USER_ERROR_PATTERNS:
        if pattern.search(text):
            return "ошибка пользователя / не прочитал инструкцию"
    for pattern in _DELIVERY_PATTERNS:
        if pattern.search(text):
            return "претензия к доставке / службе маркетплейса"
    for pattern in _EMOTIONAL_NOISE_PATTERNS:
        if pattern.search(text):
            return "эмоциональный шум без конкретики"
    # Short pure emotion without product cues.
    if len(text) < 25 and not any(p.search(text) for p in _PRODUCT_PAIN_HINTS):
        return "эмоциональный шум без конкретики"
    return None


def _extract_pain_phrase(review: str) -> str:
    """Compress a kept review into a short pain label."""

    cleaned = re.sub(r"\s+", " ", review.strip())
    # Prefer first sentence-like chunk.
    parts = re.split(r"[.!?;\n]", cleaned)
    candidate = (parts[0] if parts else cleaned).strip(" ,:-")
    if len(candidate) > 120:
        candidate = candidate[:117].rstrip() + "…"
    if not candidate:
        candidate = cleaned[:120]
    return candidate[:200]


def _badge_from_pain(pain: str) -> str:
    lower = pain.casefold()
    if any(k in lower for k in ("хлипк", "пластик", "каркас", "слом", "гнёт", "гнет")):
        return "Усиленный каркас и плотные материалы — без хлипкости"
    if any(k in lower for k in ("батаре", "аккумулятор", "заряд")):
        return "Ёмкий аккумулятор — держит заряд дольше конкурентов"
    if any(k in lower for k in ("маломер", "великомер", "размер")):
        return "Точная размерная сетка — соответствует описанию"
    if any(k in lower for k in ("выцвет", "стирк", "цвет")):
        return "Стойкий цвет — не выцветает после стирок"
    if any(k in lower for k in ("запах", "пахнет", "резин")):
        return "Без резкого запаха — безопасные материалы"
    if any(k in lower for k in ("шв", "ткан", "материал")):
        return "Аккуратные швы и прочная ткань — без брака"
    if any(k in lower for k in ("упаков", "комплект", "рассып")):
        return "Надёжная заводская упаковка — комплект целый"
    if any(k in lower for k in ("скрип", "шум")):
        return "Тихая конструкция — без скрипа и люфта"
    return f"Решение боли «{pain[:60]}» — контроль качества на производстве"


def _default_badges(product_name: str) -> list[str]:
    short = product_name[:40]
    return [
        f"{short}: усиленные материалы без хлипкости",
        "Стабильное качество — без типичного брака конкурентов",
        "Честное описание — размер и комплектация как в карточке",
        "Надёжная упаковка производителя — товар доходит целым",
    ]


def filter_and_preview_pains(request: PainAnalysisRequest) -> PainAnalysisResult:
    """Deterministic junk filter + template content (no Claude spend)."""

    junk: list[str] = []
    kept: list[str] = []
    for review in request.raw_negative_reviews:
        reason = _classify_junk(review)
        if reason is not None:
            snippet = review if len(review) <= 140 else review[:137] + "…"
            junk.append(f"{snippet} — {reason}")
        else:
            kept.append(review)

    pains: list[str] = []
    seen: set[str] = set()
    for review in kept:
        phrase = _extract_pain_phrase(review)
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        pains.append(phrase)
        if len(pains) >= 5:
            break

    insufficient = len(pains) == 0
    if insufficient:
        pains = ["Недостаточно конструктивных жалоб в выборке отзывов"]

    badges: list[str] = []
    for pain in pains[:4]:
        badges.append(_badge_from_pain(pain))
    while len(badges) < 4:
        badges.append(_default_badges(request.product_name)[len(badges)])
    badges = badges[:4]

    platform_label = "Wildberries" if request.platform == "wildberries" else "Ozon"
    pain_hook = pains[0] if pains and not insufficient else "типичные дефекты конкурентов"
    seo_title = (
        f"{request.product_name} — без «{pain_hook[:40]}» | {platform_label}"
    )[:200]
    specs_hint = (
        f" Характеристики: {request.product_specs[:180]}."
        if request.product_specs.strip()
        else ""
    )
    badge_line = "; ".join(badges)
    seo_description = (
        f"{request.product_name} для {platform_label}: закрываем боли покупателей "
        f"конкурентов. В отзывах часто жалуются на «{pain_hook}» — у нас это "
        f"проконтролировано на производстве. {badge_line}.{specs_hint} "
        "Выбирайте карточку с честным описанием и усиленным качеством."
    )[:4000]

    return PainAnalysisResult(
        filtered_out_junk=junk,
        real_product_pains=pains[:5],
        infographic_badges=badges,
        seo_title=seo_title,
        seo_description=seo_description,
        model_name="deterministic",
        insufficient_data=insufficient,
    )


def normalize_claude_pain_result(
    payload: dict[str, Any],
    *,
    model_name: str,
) -> PainAnalysisResult:
    """Validate/normalize Claude JSON into domain result."""

    pains = payload.get("real_product_pains")
    badges = payload.get("infographic_badges")
    if not isinstance(pains, list) or not pains:
        raise ValueError("Claude response missing real_product_pains.")
    if not isinstance(badges, list) or len(badges) != 4:
        raise ValueError("Claude response must include exactly 4 infographic_badges.")

    return PainAnalysisResult.model_validate(
        {
            "filtered_out_junk": payload.get("filtered_out_junk") or [],
            "real_product_pains": pains[:5],
            "infographic_badges": badges[:4],
            "seo_title": payload.get("seo_title"),
            "seo_description": payload.get("seo_description"),
            "model_name": model_name,
            "insufficient_data": False,
        }
    )


def merge_with_deterministic_fallback(
    *,
    request: PainAnalysisRequest,
    claude_result: PainAnalysisResult | None,
) -> PainAnalysisResult:
    """Prefer Claude output; fall back to deterministic preview."""

    if claude_result is not None:
        return claude_result
    return filter_and_preview_pains(request)


def build_filter_preview_payload(result: PainAnalysisResult) -> dict[str, Any]:
    """Lightweight preview payload for enqueue response / Redis stage."""

    return {
        "filtered_out_junk": list(result.filtered_out_junk),
        "real_product_pains": list(result.real_product_pains),
        "insufficient_data": result.insufficient_data,
        "junk_count": len(result.filtered_out_junk),
        "pain_count": 0
        if result.insufficient_data
        else len(result.real_product_pains),
    }
