"""Parser ↔ «Глаз Бога» bridge domain (plan §76).

When stock-parser math shows a competitor SKU gained +30% vs baseline average
sales over a 3-day window, the system emits a Vision trigger. Claude 4.7 Vision
fetches the current card photo, extracts new conversion elements, and persists
a JSON config labelled «Подтвержденный деньгами триггер».
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.stock_parser import ParserMarketplace
from app.domain.stock_sales import DailySalesEstimate, SalesWindowSummary

# Canonical Russian label stored in the generator-facing JSON config.
MONEY_CONFIRMED_TRIGGER_LABEL = "Подтвержденный деньгами триггер"
MONEY_CONFIRMED_TRIGGER_LABEL_EN = "money_confirmed_trigger"


class EyeOfGodJobStatus(StrEnum):
    """Lifecycle of one spike → Vision → JSON-config job."""

    QUEUED = "queued"
    FETCHING_IMAGE = "fetching_image"
    VISION_RUNNING = "vision_running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for Eye-of-God payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SalesSpikeConfig(StrictDomainModel):
    """Thresholds for the parser → Eye of God sales-anomaly gate."""

    recent_window_days: int = Field(default=3, ge=1, le=14)
    baseline_window_days: int = Field(default=7, ge=1, le=60)
    min_growth_ratio: float = Field(default=0.30, ge=0.0, le=10.0)
    min_baseline_daily_sales: float = Field(default=1.0, ge=0.0, le=10_000.0)
    min_recent_reliable_days: int = Field(default=2, ge=1, le=14)
    cooldown_hours: int = Field(default=24, ge=1, le=168)

    @model_validator(mode="after")
    def _validate_windows(self) -> SalesSpikeConfig:
        if self.min_recent_reliable_days > self.recent_window_days:
            raise ValueError(
                "min_recent_reliable_days must be <= recent_window_days."
            )
        return self


class SalesSpikeSignal(BaseModel):
    """Detected +30% (configurable) sales anomaly for one competitor SKU.

    Not strict: must round-trip from JSONB without losing UUID/datetime coercion.
    """

    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    marketplace: ParserMarketplace
    article: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    product_url: str | None = Field(default=None, max_length=1024)
    recent_avg_daily_sales: float = Field(ge=0.0)
    baseline_avg_daily_sales: float = Field(ge=0.0)
    growth_ratio: float
    recent_window_days: int = Field(ge=1)
    baseline_window_days: int = Field(ge=1)
    recent_units_sold: int = Field(ge=0)
    baseline_units_sold: int = Field(ge=0)
    reliable_recent_days: int = Field(ge=0)
    reliable_baseline_days: int = Field(ge=0)
    triggered_at: datetime
    image_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=10)

    @field_validator("image_urls", mode="before")
    @classmethod
    def _coerce_image_urls(cls, value: object) -> object:
        if value is None:
            return ()
        if isinstance(value, list):
            return tuple(value)
        return value

    @property
    def is_money_anomaly(self) -> bool:
        return self.growth_ratio >= 0.30


class ConversionElement(StrictDomainModel):
    """One new conversion device spotted on the current SKU photo."""

    element_type: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    placement: str = Field(min_length=1, max_length=128)
    why_it_converts: str = Field(min_length=1, max_length=500)


class MoneyConfirmedVisionResult(StrictDomainModel):
    """Claude 4.7 Vision output for a sales-spike SKU."""

    sku: str = Field(min_length=1, max_length=64)
    conversion_elements: list[ConversionElement] = Field(
        min_length=1, max_length=12
    )
    new_vs_typical_patterns: list[str] = Field(min_length=1, max_length=12)
    first_slide_hooks: list[str] = Field(min_length=1, max_length=8)
    avoid_copying: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_trace: str = Field(min_length=1, max_length=4000)


class MoneyConfirmedTriggerConfig(StrictDomainModel):
    """JSON config persisted as «Подтвержденный деньгами триггер»."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    label: str = Field(
        default=MONEY_CONFIRMED_TRIGGER_LABEL,
        min_length=1,
        max_length=128,
    )
    label_en: str = Field(
        default=MONEY_CONFIRMED_TRIGGER_LABEL_EN,
        min_length=1,
        max_length=64,
    )
    sku_id: UUID
    marketplace: str = Field(min_length=1, max_length=32)
    article: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    product_url: str | None = Field(default=None, max_length=1024)
    sales_spike: dict[str, Any]
    conversion_elements: list[ConversionElement]
    new_vs_typical_patterns: list[str] = Field(default_factory=list, max_length=12)
    first_slide_hooks: list[str] = Field(default_factory=list, max_length=8)
    avoid_copying: list[str] = Field(default_factory=list, max_length=12)
    image_urls_analyzed: list[str] = Field(default_factory=list, max_length=10)
    model_name: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_trace: str = Field(default="", max_length=4000)
    analyzed_at: datetime

    @field_validator("label", mode="before")
    @classmethod
    def _default_ru_label(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return MONEY_CONFIRMED_TRIGGER_LABEL
        return value


@dataclass(frozen=True, slots=True)
class EyeOfGodJobView:
    """Projection of a persisted Eye-of-God spike job."""

    id: UUID
    status: EyeOfGodJobStatus
    celery_task_id: str | None
    sku_id: UUID
    marketplace: str
    article: str
    title: str | None
    product_url: str | None
    spike_payload: dict[str, Any]
    image_urls: tuple[str, ...]
    vision_result: dict[str, Any] | None
    money_trigger_config: dict[str, Any] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


MONEY_CONFIRMED_VISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sku",
        "conversion_elements",
        "new_vs_typical_patterns",
        "first_slide_hooks",
        "avoid_copying",
        "confidence",
        "reasoning_trace",
    ],
    "properties": {
        "sku": {"type": "string"},
        "conversion_elements": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "element_type",
                    "description",
                    "placement",
                    "why_it_converts",
                ],
                "properties": {
                    "element_type": {"type": "string"},
                    "description": {"type": "string"},
                    "placement": {"type": "string"},
                    "why_it_converts": {"type": "string"},
                },
            },
        },
        "new_vs_typical_patterns": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "first_slide_hooks": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "avoid_copying": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "reasoning_trace": {"type": "string"},
    },
}


_EYE_OF_GOD_VISION_SYSTEM_PROMPT = (
    "You are «Глаз Бога» — a senior marketplace conversion analyst for "
    "Wildberries and Ozon. This SKU just showed a money-validated sales spike "
    "(+30% vs baseline over 3 days from stock-parser residuals). "
    "Analyze the CURRENT card photo for NEW conversion elements that likely "
    "drove the lift: badges, pain hooks, contrast accents, offer structure, "
    "infographic layout. "
    "Return ONLY valid JSON matching the schema. Do not invent elements that "
    "are not visible on the image. Prefer concrete, actionable observations."
)


def eye_of_god_vision_system_prompt() -> str:
    return _EYE_OF_GOD_VISION_SYSTEM_PROMPT


def build_eye_of_god_vision_prompt(
    *,
    sku: str,
    title: str | None,
    marketplace: str,
    growth_ratio: float,
    recent_avg_daily_sales: float,
    baseline_avg_daily_sales: float,
    recent_window_days: int,
    image_count: int,
) -> str:
    """User prompt for Claude Vision money-confirmed trigger analysis."""

    card_title = (title or sku).strip() or sku
    return (
        f"SKU конкурента {sku} ({marketplace}) получил "
        f"+{growth_ratio:.0%} к средним продажам за {recent_window_days} дня. "
        f"Название: {card_title}. "
        f"Средние продажи recent={recent_avg_daily_sales:.2f}/день vs "
        f"baseline={baseline_avg_daily_sales:.2f}/день. "
        f"Изображений: {image_count}. "
        "Проанализируй текущую фотографию на НОВЫЕ конверсионные элементы. "
        "Результат будет сохранён как «Подтвержденный деньгами триггер». "
        "Сначала рассуждай в reasoning_trace, затем заполни JSON. "
        f"Поле sku в ответе должно быть ровно: {sku}."
    )


def _avg_daily(units: Sequence[DailySalesEstimate]) -> tuple[float, int, int]:
    """Return (avg_daily_sales, reliable_day_count, total_units_sold)."""

    reliable = [day for day in units if day.is_reliable]
    if not reliable:
        return 0.0, 0, 0
    total = sum(day.units_sold for day in reliable)
    return total / float(len(reliable)), len(reliable), total


def detect_sales_spike(
    summary: SalesWindowSummary,
    *,
    sku_id: UUID,
    marketplace: ParserMarketplace,
    article: str,
    title: str | None = None,
    product_url: str | None = None,
    triggered_at: datetime,
    config: SalesSpikeConfig | None = None,
    image_urls: Sequence[str] = (),
) -> SalesSpikeSignal | None:
    """Return a spike signal when recent 3-day avg is ≥ +30% vs baseline avg.

    ``summary.days`` must be ordered ascending by day. Recent window = last N
    reliable-capable estimates; baseline = the N days immediately before.
    """

    cfg = config or SalesSpikeConfig()
    days = list(summary.days)
    need = cfg.recent_window_days + cfg.baseline_window_days
    if len(days) < need:
        return None

    recent_slice = days[-cfg.recent_window_days :]
    baseline_slice = days[
        -(cfg.recent_window_days + cfg.baseline_window_days) : -cfg.recent_window_days
    ]

    recent_avg, recent_reliable, recent_units = _avg_daily(recent_slice)
    baseline_avg, baseline_reliable, baseline_units = _avg_daily(baseline_slice)

    if recent_reliable < cfg.min_recent_reliable_days:
        return None
    if baseline_avg < cfg.min_baseline_daily_sales:
        return None
    if baseline_reliable < 1:
        return None

    growth = (recent_avg - baseline_avg) / baseline_avg
    if growth < cfg.min_growth_ratio:
        return None

    cleaned_urls = tuple(
        url.strip()
        for url in image_urls
        if isinstance(url, str) and url.strip()
    )[:10]

    return SalesSpikeSignal(
        sku_id=sku_id,
        marketplace=marketplace,
        article=article.strip(),
        title=title,
        product_url=product_url,
        recent_avg_daily_sales=round(recent_avg, 4),
        baseline_avg_daily_sales=round(baseline_avg, 4),
        growth_ratio=round(growth, 4),
        recent_window_days=cfg.recent_window_days,
        baseline_window_days=cfg.baseline_window_days,
        recent_units_sold=recent_units,
        baseline_units_sold=baseline_units,
        reliable_recent_days=recent_reliable,
        reliable_baseline_days=baseline_reliable,
        triggered_at=triggered_at,
        image_urls=cleaned_urls,
    )


def build_money_confirmed_trigger_config(
    *,
    spike: SalesSpikeSignal,
    vision: MoneyConfirmedVisionResult,
    model_name: str,
    analyzed_at: datetime,
    image_urls_analyzed: Sequence[str] | None = None,
) -> MoneyConfirmedTriggerConfig:
    """Assemble the generator JSON labelled «Подтвержденный деньгами триггер»."""

    urls = list(image_urls_analyzed) if image_urls_analyzed is not None else list(
        spike.image_urls
    )
    return MoneyConfirmedTriggerConfig(
        schema_version="1.0",
        label=MONEY_CONFIRMED_TRIGGER_LABEL,
        label_en=MONEY_CONFIRMED_TRIGGER_LABEL_EN,
        sku_id=spike.sku_id,
        marketplace=spike.marketplace.value,
        article=spike.article,
        title=spike.title,
        product_url=spike.product_url,
        sales_spike={
            "recent_avg_daily_sales": spike.recent_avg_daily_sales,
            "baseline_avg_daily_sales": spike.baseline_avg_daily_sales,
            "growth_ratio": spike.growth_ratio,
            "recent_window_days": spike.recent_window_days,
            "baseline_window_days": spike.baseline_window_days,
            "recent_units_sold": spike.recent_units_sold,
            "baseline_units_sold": spike.baseline_units_sold,
            "reliable_recent_days": spike.reliable_recent_days,
            "reliable_baseline_days": spike.reliable_baseline_days,
            "triggered_at": spike.triggered_at.isoformat(),
        },
        conversion_elements=list(vision.conversion_elements),
        new_vs_typical_patterns=list(vision.new_vs_typical_patterns),
        first_slide_hooks=list(vision.first_slide_hooks),
        avoid_copying=list(vision.avoid_copying),
        image_urls_analyzed=urls[:10],
        model_name=model_name.strip(),
        confidence=vision.confidence,
        reasoning_trace=vision.reasoning_trace,
        analyzed_at=analyzed_at,
    )


def dump_money_trigger_config(config: MoneyConfirmedTriggerConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def money_trigger_config_json(config: MoneyConfirmedTriggerConfig) -> str:
    """Canonical JSON string for generator / analytics hand-off."""

    return json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)


def redis_eye_of_god_key(job_id: UUID, stage: str) -> str:
    return f"claude:eye_of_god:{job_id}:{stage}"


def wildberries_primary_image_urls(nm_id: int, *, count: int = 1) -> tuple[str, ...]:
    """Build WB CDN URLs for the current main card photo(s).

    Basket host shards by nm volume; structure is stable vs HTML scrapers.
    """

    if nm_id <= 0:
        return ()
    vol = nm_id // 100_000
    part = nm_id // 1_000
    # Host index heuristic used by WB CDN (0–12 range historically).
    basket = vol % 13
    host = f"https://basket-{basket:02d}.wbbasket.ru"
    urls: list[str] = []
    for index in range(1, max(1, count) + 1):
        urls.append(f"{host}/vol{vol}/part{part}/{nm_id}/images/big/{index}.webp")
    return tuple(urls)
