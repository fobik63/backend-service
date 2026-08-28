"""Domain models for marketplace SEO copy generation (WB / Ozon)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

WB_DESCRIPTION_MAX_CHARS = 5000
OZON_DESCRIPTION_MAX_CHARS = 10_000
TITLE_MAX_CHARS = 180
BENEFITS_MIN = 4
BENEFITS_MAX = 6
DESCRIPTION_TARGET_MIN_CHARS = 800
DESCRIPTION_TARGET_MAX_CHARS = 1200

SEO_SYSTEM_PROMPT = (
    "Ты профессиональный e-commerce копирайтер. "
    "Напиши подробное продающее SEO-описание товара "
    f"(от {DESCRIPTION_TARGET_MIN_CHARS} до {DESCRIPTION_TARGET_MAX_CHARS} символов) "
    "с ключевыми словами, преимуществами, характеристиками и закрытием болей покупателя. "
    "Не описывай визуальные элементы фото."
)


class SeoTargetPlatform(StrEnum):
    WB = "wb"
    OZON = "ozon"


class SeoTextError(Exception):
    """Base SEO text domain/application failure."""


class SeoTextConfigurationError(SeoTextError):
    """Missing or invalid OpenAI / LLM credentials."""


class SeoTextValidationError(SeoTextError, ValueError):
    """Invalid client input for SEO generation."""


class SeoTextUpstreamError(SeoTextError):
    """OpenAI request failed or returned an unusable payload."""


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class SeoTextGenerateRequest(DomainModel):
    """Normalized input for SEO title / benefits / description generation."""

    title: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., min_length=1, max_length=256)
    features: Mapping[str, Any] = Field(default_factory=dict)
    target_platform: SeoTargetPlatform

    @field_validator("title", "category", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def description_max_chars(self) -> int:
        if self.target_platform is SeoTargetPlatform.WB:
            return WB_DESCRIPTION_MAX_CHARS
        return OZON_DESCRIPTION_MAX_CHARS


class SeoTokenUsage(DomainModel):
    """Token accounting from the upstream LLM response."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class SeoTextContent(DomainModel):
    """Generated marketplace SEO artifacts."""

    optimized_title: str = Field(..., min_length=1, max_length=TITLE_MAX_CHARS)
    benefits: tuple[str, ...] = Field(
        ...,
        min_length=BENEFITS_MIN,
        max_length=BENEFITS_MAX,
    )
    description: str = Field(
        ...,
        min_length=DESCRIPTION_TARGET_MIN_CHARS,
        max_length=OZON_DESCRIPTION_MAX_CHARS,
    )

    @field_validator("benefits", mode="before")
    @classmethod
    def _normalize_benefits(cls, value: object) -> object:
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return tuple(cleaned)
        if isinstance(value, tuple):
            cleaned = tuple(str(item).strip() for item in value if str(item).strip())
            return cleaned
        return value

    @field_validator("optimized_title", "description", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SeoTextGenerateResult(DomainModel):
    """Full generation outcome including billing and token usage."""

    content: SeoTextContent
    usage: SeoTokenUsage
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)


class SeoTextBatchGenerateResult(DomainModel):
    """Partial batch outcome when coins run out mid-generation."""

    items: tuple[SeoTextGenerateResult, ...] = ()
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    stopped_reason: str | None = None


def description_limit_for(platform: SeoTargetPlatform) -> int:
    """Return the marketplace description character cap."""

    if platform is SeoTargetPlatform.WB:
        return WB_DESCRIPTION_MAX_CHARS
    return OZON_DESCRIPTION_MAX_CHARS
