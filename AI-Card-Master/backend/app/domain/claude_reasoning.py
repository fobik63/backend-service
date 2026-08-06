"""Domain models for Claude 4.7 Vision + Chain-of-Thought reasoning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaudeReasoningJobStatus(StrEnum):
    """Lifecycle of an async Claude reasoning job."""

    QUEUED = "queued"
    VISION_RUNNING = "vision_running"
    REASONING_RUNNING = "reasoning_running"
    COMPLETED = "completed"
    FAILED = "failed"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for Claude structured payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class VisualTrigger(StrictDomainModel):
    """One conversion-oriented visual cue found on a competitor card."""

    trigger_id: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    location: str = Field(min_length=1, max_length=128)
    contrast_role: str = Field(min_length=1, max_length=128)
    pain_addressed: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)


class VisionStageResult(StrictDomainModel):
    """Structured output of the Vision / visual-trigger stage."""

    slide_summary: str = Field(min_length=1, max_length=1000)
    color_palette: list[str] = Field(min_length=1, max_length=12)
    layout_pattern: str = Field(min_length=1, max_length=300)
    visual_triggers: list[VisualTrigger] = Field(min_length=1, max_length=20)
    blind_spots: list[str] = Field(default_factory=list, max_length=20)
    reasoning_trace: str = Field(min_length=1, max_length=4000)


class TextAlignmentItem(StrictDomainModel):
    """How one visual trigger maps onto competitor text evidence."""

    trigger_id: str = Field(min_length=1, max_length=64)
    text_evidence: str = Field(min_length=1, max_length=500)
    alignment: str = Field(min_length=1, max_length=32)
    gap_note: str = Field(min_length=1, max_length=500)
    monetization_signal: str = Field(min_length=1, max_length=300)


class ReasoningStageResult(StrictDomainModel):
    """Structured output of the text-alignment / CoT stage."""

    alignments: list[TextAlignmentItem] = Field(min_length=1, max_length=20)
    confirmed_triggers: list[str] = Field(min_length=0, max_length=20)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    strategic_insights: list[str] = Field(min_length=1, max_length=12)
    reasoning_trace: str = Field(min_length=1, max_length=4000)


class ChainOfThoughtResult(StrictDomainModel):
    """Final combined Vision → Reasoning payload for the frontend / generator."""

    vision: VisionStageResult
    reasoning: ReasoningStageResult
    conversion_triggers: list[str] = Field(min_length=1, max_length=20)
    actionable_blueprint: str = Field(min_length=1, max_length=4000)
    confidence_score: float = Field(ge=0.0, le=1.0)
    model_name: str = Field(min_length=1, max_length=128)


class CompetitorTextContext(StrictDomainModel):
    """Textual competitor data fed into the second CoT stage."""

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=8000)
    characteristics: list[str] = Field(default_factory=list, max_length=40)
    reviews_positive: list[str] = Field(default_factory=list, max_length=50)
    reviews_negative: list[str] = Field(default_factory=list, max_length=50)
    price_before: float | None = Field(default=None, ge=0)
    price_after: float | None = Field(default=None, ge=0)
    marketplace: str | None = Field(default=None, max_length=32)
    product_category: str | None = Field(default=None, max_length=128)

    @field_validator("characteristics", "reviews_positive", "reviews_negative", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("List items must be strings.")
            text = item.strip()
            if text:
                cleaned.append(text)
        return cleaned


@dataclass(frozen=True, slots=True)
class ClaudeReasoningJobView:
    """Projection of a persisted Claude reasoning job."""

    id: UUID
    user_id: UUID
    status: ClaudeReasoningJobStatus
    celery_task_id: str | None
    image_object_keys: tuple[str, ...]
    text_context: dict[str, Any]
    vision_result: dict[str, Any] | None
    reasoning_result: dict[str, Any] | None
    final_result: dict[str, Any] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


VISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "slide_summary",
        "color_palette",
        "layout_pattern",
        "visual_triggers",
        "blind_spots",
        "reasoning_trace",
    ],
    "properties": {
        "slide_summary": {"type": "string"},
        "color_palette": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "layout_pattern": {"type": "string"},
        "visual_triggers": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "trigger_id",
                    "category",
                    "description",
                    "location",
                    "contrast_role",
                    "pain_addressed",
                    "confidence",
                ],
                "properties": {
                    "trigger_id": {"type": "string"},
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "contrast_role": {"type": "string"},
                    "pain_addressed": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "blind_spots": {"type": "array", "items": {"type": "string"}},
        "reasoning_trace": {"type": "string"},
    },
}


REASONING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "alignments",
        "confirmed_triggers",
        "contradictions",
        "strategic_insights",
        "reasoning_trace",
    ],
    "properties": {
        "alignments": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "trigger_id",
                    "text_evidence",
                    "alignment",
                    "gap_note",
                    "monetization_signal",
                ],
                "properties": {
                    "trigger_id": {"type": "string"},
                    "text_evidence": {"type": "string"},
                    "alignment": {"type": "string"},
                    "gap_note": {"type": "string"},
                    "monetization_signal": {"type": "string"},
                },
            },
        },
        "confirmed_triggers": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "strategic_insights": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "reasoning_trace": {"type": "string"},
    },
}


_VISION_SYSTEM_PROMPT = (
    "You are a senior marketplace visual strategist for Wildberries and Ozon. "
    "Analyze competitor product-card images with Claude Vision. "
    "Think step-by-step about conversion triggers visible on the slides, "
    "then return ONLY valid JSON matching the requested schema. "
    "Do not invent elements that are not visible. "
    "Put your intermediate visual reasoning into reasoning_trace."
)

_REASONING_SYSTEM_PROMPT = (
    "You are a senior marketplace conversion analyst. "
    "You receive visual triggers already extracted from competitor images "
    "and textual marketplace data (title, description, specs, reviews). "
    "Continue the chain-of-thought: first verify each visual trigger against "
    "the text evidence, then produce strategic insights. "
    "Return ONLY valid JSON matching the requested schema. "
    "Never invent reviews, specs, or prices that are absent from the input. "
    "Put your intermediate reasoning into reasoning_trace."
)


def build_vision_user_prompt(*, product_category: str | None, image_count: int) -> str:
    """Prompt for stage-1 visual trigger extraction."""

    category = (product_category or "не указана").strip() or "не указана"
    return (
        f"Проанализируй {image_count} изображений карточки конкурента. "
        f"Категория товара: {category}. "
        "Этап 1 цепочки рассуждений (Vision): выдели визуальные триггеры конверсии "
        "(плашки болей, контрастные акценты, оффер на первом слайде, композицию). "
        "Сначала опиши ход рассуждений в reasoning_trace, затем заполни JSON. "
        "Структура строго по схеме VisionStageResult."
    )


def build_reasoning_user_prompt(
    *,
    vision: VisionStageResult,
    text_context: CompetitorTextContext,
) -> str:
    """Prompt for stage-2 visual↔text alignment."""

    payload = {
        "visual_triggers": [item.model_dump() for item in vision.visual_triggers],
        "slide_summary": vision.slide_summary,
        "layout_pattern": vision.layout_pattern,
        "blind_spots": vision.blind_spots,
        "competitor_text": text_context.model_dump(exclude_none=True),
    }
    return (
        "Этап 2 цепочки рассуждений: сопоставь визуальные триггеры конкурента "
        "с текстовыми данными (заголовок, описание, характеристики, отзывы). "
        "Для каждого trigger_id укажи alignment: confirmed | partial | contradiction | missing. "
        "Сначала рассуждай в reasoning_trace, затем верни строго JSON. "
        f"Входные данные:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def vision_system_prompt() -> str:
    return _VISION_SYSTEM_PROMPT


def reasoning_system_prompt() -> str:
    return _REASONING_SYSTEM_PROMPT


def merge_chain_of_thought(
    *,
    vision: VisionStageResult,
    reasoning: ReasoningStageResult,
    model_name: str,
) -> ChainOfThoughtResult:
    """Compose the final structured CoT result from both stages."""

    confirmed = list(reasoning.confirmed_triggers)
    if not confirmed:
        confirmed = [
            item.trigger_id
            for item in reasoning.alignments
            if item.alignment.lower() in {"confirmed", "partial"}
        ]
    if not confirmed:
        confirmed = [trigger.trigger_id for trigger in vision.visual_triggers[:3]]

    trigger_lookup = {item.trigger_id: item for item in vision.visual_triggers}
    conversion_triggers: list[str] = []
    for trigger_id in confirmed:
        trigger = trigger_lookup.get(trigger_id)
        if trigger is None:
            conversion_triggers.append(trigger_id)
        else:
            conversion_triggers.append(
                f"{trigger.category}: {trigger.description} (pain: {trigger.pain_addressed})"
            )

    blueprint_parts = [
        "Использовать подтверждённые деньгами визуальные триггеры конкурента:",
        *[f"- {line}" for line in conversion_triggers[:8]],
        "Стратегические инсайты:",
        *[f"- {line}" for line in reasoning.strategic_insights[:6]],
    ]
    if reasoning.contradictions:
        blueprint_parts.append("Противоречия визуал↔текст (избегать копирования):")
        blueprint_parts.extend(f"- {line}" for line in reasoning.contradictions[:6])

    confidences = [item.confidence for item in vision.visual_triggers]
    avg_vision = sum(confidences) / len(confidences) if confidences else 0.5
    confirmed_ratio = (
        len([a for a in reasoning.alignments if a.alignment.lower() == "confirmed"])
        / max(len(reasoning.alignments), 1)
    )
    confidence_score = round(min(1.0, max(0.0, 0.55 * avg_vision + 0.45 * confirmed_ratio)), 4)

    return ChainOfThoughtResult(
        vision=vision,
        reasoning=reasoning,
        conversion_triggers=conversion_triggers,
        actionable_blueprint="\n".join(blueprint_parts),
        confidence_score=confidence_score,
        model_name=model_name,
    )


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating fenced markdown."""

    raw = raw_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match is None:
            raise ValueError("Claude response does not contain a JSON object.")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Claude JSON root must be an object.")
    return payload


def redis_stage_key(job_id: UUID, stage: str) -> str:
    """Redis key for an intermediate CoT stage payload."""

    return f"claude:reasoning:{job_id}:{stage}"
