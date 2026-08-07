"""Fail-Safe Export sandbox — pre-WB/Ozon validation + Claude auto-fix (plan §59).

Checks (deterministic):
1. Photo weight / size / resolution (delegates to ``validate_card_for_marketplace``).
2. Forbidden marketplace lexicon in title / description / characteristics.
3. Category extras required by seller APIs (WB subject_id, Ozon category+type).

On errors, Claude 4.7 proposes a corrected card payload (text + category hints).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.export import (
    CardValidationReport,
    ImageAssetMeta,
    MarketplacePlatform,
    ValidationIssue,
    ValidationSeverity,
    validate_card_for_marketplace,
)

# ---------------------------------------------------------------------------
# Forbidden lexicon (marketplace ToS / advertising practice — RU + EN)
# ---------------------------------------------------------------------------

# Shared stop-words that commonly trigger moderation on WB / Ozon listings.
_SHARED_FORBIDDEN: frozenset[str] = frozenset(
    {
        # Medical / absolute claims
        "гарантированное лечение",
        "вылечит",
        "100% излечение",
        "избавит от рака",
        "лечит рак",
        "антиковид",
        "anti-covid",
        # Superlatives / misleading guarantees
        "лучший в мире",
        "номер 1 в мире",
        "гарантия 100%",
        "гарантией 100%",
        "100% гарантия",
        "абсолютно безопасен",
        "без побочных",
        # Restricted product cues
        "рецептурный препарат",
        "наркотик",
        "марихуана",
        "cannabis",
        "cbd масло",
        "снюс",
        "вейп жидкость никотин",
        # Competitor / brand abuse
        "подделка оригинала",
        "копия бренда",
        "реплика louis",
        "fake authentic",
        # Aggressive spam / clickbait
        "только сегодня скидка",
        "нажми сюда",
        "бесплатно!!!",
        "click here now",
        "viagra",
        "виагра",
        "cialis",
        "сиалис",
    }
)

_PLATFORM_FORBIDDEN: Mapping[MarketplacePlatform, frozenset[str]] = {
    MarketplacePlatform.WILDBERRIES: _SHARED_FORBIDDEN
    | frozenset(
        {
            "wildberries сам рекомендует",
            "wb рекомендует этот товар",
            "официальный магазин wildberries",
        }
    ),
    MarketplacePlatform.OZON: _SHARED_FORBIDDEN
    | frozenset(
        {
            "ozon рекомендует",
            "официальный магазин ozon",
            "выбор ozon принудительно",
        }
    ),
    MarketplacePlatform.AMAZON: _SHARED_FORBIDDEN
    | frozenset(
        {
            "amazon's choice guaranteed",
            "official amazon store fake",
        }
    ),
}

# Whole-word / phrase scan (case-insensitive). Multi-word phrases use substring.
_WORD_BOUNDARY_RE_CACHE: dict[str, re.Pattern[str]] = {}


def forbidden_lexicon_for(platform: MarketplacePlatform) -> frozenset[str]:
    """Return the fail-safe stop-word set for a marketplace."""

    return _PLATFORM_FORBIDDEN.get(platform, _SHARED_FORBIDDEN)


def _pattern_for_term(term: str) -> re.Pattern[str]:
    key = term.casefold()
    cached = _WORD_BOUNDARY_RE_CACHE.get(key)
    if cached is not None:
        return cached
    if " " in key or "-" in key:
        pattern = re.compile(re.escape(key), re.IGNORECASE)
    else:
        pattern = re.compile(rf"(?<!\w){re.escape(key)}(?!\w)", re.IGNORECASE)
    _WORD_BOUNDARY_RE_CACHE[key] = pattern
    return pattern


def scan_forbidden_words(
    *,
    platform: MarketplacePlatform,
    title: str,
    description: str,
    characteristics: tuple[str, ...],
) -> tuple[ValidationIssue, ...]:
    """Flag marketplace-forbidden phrases in card text fields."""

    lexicon = forbidden_lexicon_for(platform)
    fields: list[tuple[str, str]] = [
        ("title", title),
        ("description", description),
    ]
    for index, item in enumerate(characteristics):
        fields.append((f"characteristics[{index}]", item))

    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()
    for field, value in fields:
        haystack = value or ""
        if not haystack.strip():
            continue
        for term in lexicon:
            if not _pattern_for_term(term).search(haystack):
                continue
            marker = (field, term.casefold())
            if marker in seen:
                continue
            seen.add(marker)
            issues.append(
                ValidationIssue(
                    code="FORBIDDEN_WORD",
                    field=field,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Forbidden marketplace phrase «{term}» found in {field}."
                    ),
                )
            )
    return tuple(issues)


# ---------------------------------------------------------------------------
# Category correctness (seller API extras)
# ---------------------------------------------------------------------------

_POSITIVE_INT_KEYS: Mapping[MarketplacePlatform, tuple[str, ...]] = {
    MarketplacePlatform.WILDBERRIES: ("subject_id",),
    MarketplacePlatform.OZON: ("description_category_id", "type_id"),
    MarketplacePlatform.AMAZON: ("product_type",),  # string product type for SP-API
}


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_category_extras(
    *,
    platform: MarketplacePlatform,
    extras: Mapping[str, Any] | None,
    product_category: str | None = None,
    require_category_ids: bool = True,
) -> tuple[ValidationIssue, ...]:
    """Ensure marketplace category identifiers are present and coherent."""

    payload = dict(extras or {})
    issues: list[ValidationIssue] = []

    if platform is MarketplacePlatform.AMAZON:
        product_type = payload.get("product_type")
        if require_category_ids and (
            not isinstance(product_type, str) or not product_type.strip()
        ):
            issues.append(
                ValidationIssue(
                    code="CATEGORY_MISSING",
                    field="extras.product_type",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        "Amazon export requires extras.product_type "
                        "(SP-API listing product type)."
                    ),
                )
            )
    else:
        for key in _POSITIVE_INT_KEYS.get(platform, ()):
            raw = payload.get(key)
            if not require_category_ids and raw is None:
                continue
            if not _is_positive_int(raw):
                issues.append(
                    ValidationIssue(
                        code="CATEGORY_MISSING",
                        field=f"extras.{key}",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"{platform.value} export requires extras.{key} "
                            f"(positive integer category / subject id)."
                        ),
                    )
                )

    category_hint = (product_category or "").strip()
    if category_hint and len(category_hint) < 2:
        issues.append(
            ValidationIssue(
                code="CATEGORY_INVALID",
                field="product_category",
                severity=ValidationSeverity.ERROR,
                message="product_category is too short to map to a marketplace taxonomy.",
            )
        )

    # Soft coherence: free-text niche vs numeric ids already supplied.
    if category_hint and platform is MarketplacePlatform.WILDBERRIES:
        subject_id = payload.get("subject_id")
        if _is_positive_int(subject_id) and category_hint.isdigit():
            if int(category_hint) != subject_id:
                issues.append(
                    ValidationIssue(
                        code="CATEGORY_MISMATCH",
                        field="extras.subject_id",
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"product_category «{category_hint}» does not match "
                            f"extras.subject_id={subject_id}."
                        ),
                    )
                )

    if category_hint and platform is MarketplacePlatform.OZON:
        type_id = payload.get("type_id")
        if _is_positive_int(type_id) and category_hint.isdigit():
            if int(category_hint) != type_id:
                issues.append(
                    ValidationIssue(
                        code="CATEGORY_MISMATCH",
                        field="extras.type_id",
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"product_category «{category_hint}» does not match "
                            f"extras.type_id={type_id}."
                        ),
                    )
                )

    return tuple(issues)


# ---------------------------------------------------------------------------
# Sandbox orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FailSafeSandboxReport:
    """Full pre-export sandbox outcome (limits + lexicon + category)."""

    validation: CardValidationReport
    forbidden_hits: int
    category_errors: int

    @property
    def is_valid(self) -> bool:
        return self.validation.is_valid

    @property
    def platform(self) -> MarketplacePlatform:
        return self.validation.platform


def run_fail_safe_sandbox(
    *,
    platform: MarketplacePlatform,
    title: str,
    description: str,
    characteristics: tuple[str, ...],
    images: tuple[ImageAssetMeta, ...],
    extras: Mapping[str, Any] | None = None,
    product_category: str | None = None,
    require_category_ids: bool = False,
) -> FailSafeSandboxReport:
    """Run photo/weight + forbidden-words + category checks before export.

    ``require_category_ids`` defaults to False for ``/validate`` (seller may
    not have picked taxonomy yet). Export draft path should pass True.
    """

    base = validate_card_for_marketplace(
        platform=platform,
        title=title,
        description=description,
        characteristics=characteristics,
        images=images,
    )
    forbidden = scan_forbidden_words(
        platform=platform,
        title=title,
        description=description,
        characteristics=characteristics,
    )
    category = validate_category_extras(
        platform=platform,
        extras=extras,
        product_category=product_category,
        require_category_ids=require_category_ids,
    )
    merged = tuple(base.issues) + forbidden + category
    has_errors = any(i.severity is ValidationSeverity.ERROR for i in merged)
    report = CardValidationReport(
        platform=base.platform,
        is_valid=not has_errors,
        issues=merged,
        title_length=base.title_length,
        description_length=base.description_length,
        photo_count=base.photo_count,
        requirements=base.requirements,
    )
    return FailSafeSandboxReport(
        validation=report,
        forbidden_hits=sum(1 for i in forbidden if i.code == "FORBIDDEN_WORD"),
        category_errors=sum(
            1
            for i in category
            if i.severity is ValidationSeverity.ERROR
            and i.code.startswith("CATEGORY_")
        ),
    )


# ---------------------------------------------------------------------------
# Claude 4.7 auto-fix suggestion
# ---------------------------------------------------------------------------


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for Fail-Safe Claude payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ExportFixSuggestion(StrictDomainModel):
    """Corrected card payload proposed by Claude after sandbox errors."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=8000)
    characteristics: list[str] = Field(default_factory=list, max_length=20)
    category_hint: str = Field(default="", max_length=256)
    suggested_subject_id: int | None = Field(default=None, ge=1)
    suggested_description_category_id: int | None = Field(default=None, ge=1)
    suggested_type_id: int | None = Field(default=None, ge=1)
    suggested_product_type: str = Field(default="", max_length=128)
    fix_summary: str = Field(min_length=1, max_length=2000)
    removed_phrases: list[str] = Field(default_factory=list, max_length=40)
    model_name: str = Field(default="", max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("characteristics", "removed_phrases", mode="before")
    @classmethod
    def _clean_str_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("List items must be strings.")
            text = " ".join(item.strip().split())
            if text:
                cleaned.append(text[:500])
        return cleaned

    @field_validator("title", "description", "category_hint", "fix_summary", "suggested_product_type", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


EXPORT_FIX_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "description",
        "characteristics",
        "category_hint",
        "fix_summary",
        "removed_phrases",
        "confidence",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": "string", "minLength": 1, "maxLength": 8000},
        "characteristics": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "category_hint": {"type": "string", "maxLength": 256},
        "suggested_subject_id": {"type": ["integer", "null"], "minimum": 1},
        "suggested_description_category_id": {"type": ["integer", "null"], "minimum": 1},
        "suggested_type_id": {"type": ["integer", "null"], "minimum": 1},
        "suggested_product_type": {"type": "string", "maxLength": 128},
        "fix_summary": {"type": "string", "minLength": 1, "maxLength": 2000},
        "removed_phrases": {
            "type": "array",
            "maxItems": 40,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

_EXPORT_FIX_SYSTEM_PROMPT = (
    "Ты — старший комплаенс-редактор карточек товаров для маркетплейсов "
    "Wildberries / Ozon / Amazon. Твоя задача: по списку ошибок валидатора "
    "предложить ИСПРАВЛЕННЫЙ вариант title/description/characteristics и "
    "подсказку по категории. Не выдумывай медицинские чудеса и запрещённые "
    "обещания. Соблюдай лимиты символов платформы. Ответ строго JSON."
)


def export_fix_system_prompt() -> str:
    """System prompt for Claude Fail-Safe auto-fix."""

    return _EXPORT_FIX_SYSTEM_PROMPT


def build_export_fix_prompt(
    *,
    platform: MarketplacePlatform,
    title: str,
    description: str,
    characteristics: tuple[str, ...],
    issues: tuple[ValidationIssue, ...],
    product_category: str | None = None,
    extras: Mapping[str, Any] | None = None,
    title_max: int,
    description_max: int,
    characteristics_max: int,
    characteristic_max_length: int,
) -> str:
    """User prompt with current card + sandbox errors for Claude rewrite."""

    issue_lines = [
        f"- [{issue.severity.value}] {issue.code}"
        + (f" ({issue.field})" if issue.field else "")
        + f": {issue.message}"
        for issue in issues
    ]
    chars_block = "\n".join(f"  - {item}" for item in characteristics) or "  (none)"
    extras_json = {k: extras[k] for k in sorted(extras or {})}
    return (
        f"Платформа: {platform.value}\n"
        f"Лимиты: title≤{title_max}, description≤{description_max}, "
        f"characteristics≤{characteristics_max} (каждый ≤{characteristic_max_length}).\n"
        f"product_category: {product_category or '(не задана)'}\n"
        f"extras: {extras_json}\n\n"
        f"ТЕКУЩИЙ TITLE:\n{title}\n\n"
        f"ТЕКУЩЕЕ DESCRIPTION:\n{description}\n\n"
        f"CHARACTERISTICS:\n{chars_block}\n\n"
        f"ОШИБКИ ВАЛИДАТОРА-ПЕСОЧНИЦЫ:\n"
        + ("\n".join(issue_lines) if issue_lines else "- (нет)")
        + "\n\n"
        "Верни исправленные title, description, characteristics без запрещённых "
        "фраз; уложись в лимиты; заполни category_hint и numeric id-подсказки "
        "только если уверен (иначе null). В removed_phrases перечисли удалённые "
        "запрещённые выражения. confidence — уверенность 0..1."
    )


def normalize_export_fix_payload(
    payload: Mapping[str, Any],
    *,
    model_name: str,
) -> ExportFixSuggestion:
    """Validate Claude JSON into ``ExportFixSuggestion``."""

    data = dict(payload)
    data.pop("schema_version", None)
    data.pop("model_name", None)
    suggestion = ExportFixSuggestion.model_validate(data)
    return suggestion.model_copy(
        update={
            "schema_version": "1.0",
            "model_name": model_name.strip()[:128],
        }
    )


@dataclass(frozen=True, slots=True)
class FailSafeSandboxResult:
    """API-facing sandbox result: validation report + optional Claude fix."""

    sandbox: FailSafeSandboxReport
    suggested_fix: ExportFixSuggestion | None
    claude_fix_attempted: bool
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0

    @property
    def is_valid(self) -> bool:
        return self.sandbox.is_valid

    @property
    def platform(self) -> MarketplacePlatform:
        return self.sandbox.platform
