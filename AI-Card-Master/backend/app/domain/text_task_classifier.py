"""Local text-task classifier — filter simple workloads before Claude (C6).

Heuristic + optional Ollama JSON pass decide whether a routine text job can
stay on LOCAL (Ollama) or must escalate to Claude Haiku/Sonnet.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.smart_reasoning import ReasoningTaskKind
from app.domain.semantic_filter import estimate_text_tokens


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TextTaskComplexity(StrEnum):
    """Routing hint from the local classifier."""

    SIMPLE = "simple"
    NEEDS_CLAUDE = "needs_claude"


TEXT_TASK_CLASSIFICATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["complexity", "reason"],
    "properties": {
        "complexity": {
            "type": "string",
            "enum": [TextTaskComplexity.SIMPLE.value, TextTaskComplexity.NEEDS_CLAUDE.value],
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 300},
    },
}


class TextTaskClassification(StrictDomainModel):
    """Classifier decision for one text workload."""

    complexity: TextTaskComplexity
    reason: str = Field(min_length=1, max_length=300)
    estimated_tokens: int = Field(default=0, ge=0)
    used_local_llm: bool = False

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


# Task kinds the local pre-filter may keep off Claude entirely.
_CLASSIFIABLE_KINDS: frozenset[ReasoningTaskKind] = frozenset(
    {
        ReasoningTaskKind.PAIN_ANALYSIS,
        ReasoningTaskKind.ORACLE_ENRICHMENT,
        ReasoningTaskKind.AB_HYPOTHESES,
        ReasoningTaskKind.AI_STRATEGY,
        ReasoningTaskKind.TEXT_CLASSIFICATION,
        ReasoningTaskKind.SEMANTIC_COMPRESSION,
        ReasoningTaskKind.ZERO_HALLUCINATION,
        ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX,
    }
)

_SIMPLE_TOKEN_SOFT = 2_500
_SIMPLE_TOKEN_HARD = 8_000
_SIMPLE_REVIEW_SOFT = 40


def is_classifiable_text_task(
    kind: ReasoningTaskKind,
    *,
    has_vision: bool = False,
) -> bool:
    """True when the workload may be pre-filtered by the local classifier."""

    if has_vision:
        return False
    return kind in _CLASSIFIABLE_KINDS


def classify_text_task_heuristic(
    *,
    kind: ReasoningTaskKind,
    text_blob: str,
    item_count: int = 0,
    has_vision: bool = False,
) -> TextTaskClassification:
    """Cheap deterministic pre-filter (no LLM) before optional Ollama pass."""

    if has_vision or kind not in _CLASSIFIABLE_KINDS:
        return TextTaskClassification(
            complexity=TextTaskComplexity.NEEDS_CLAUDE,
            reason="vision_or_non_classifiable_task",
            estimated_tokens=estimate_text_tokens(text_blob),
            used_local_llm=False,
        )

    tokens = estimate_text_tokens(text_blob)
    if tokens > _SIMPLE_TOKEN_HARD or item_count > _SIMPLE_REVIEW_SOFT * 2:
        return TextTaskClassification(
            complexity=TextTaskComplexity.NEEDS_CLAUDE,
            reason=f"oversized_context tokens={tokens} items={item_count}",
            estimated_tokens=tokens,
            used_local_llm=False,
        )
    if tokens <= _SIMPLE_TOKEN_SOFT and item_count <= _SIMPLE_REVIEW_SOFT:
        return TextTaskClassification(
            complexity=TextTaskComplexity.SIMPLE,
            reason=f"small_text_workload tokens={tokens} items={item_count}",
            estimated_tokens=tokens,
            used_local_llm=False,
        )
    return TextTaskClassification(
        complexity=TextTaskComplexity.NEEDS_CLAUDE,
        reason=f"borderline_context tokens={tokens} items={item_count}",
        estimated_tokens=tokens,
        used_local_llm=False,
    )


def normalize_classification_payload(
    payload: Mapping[str, Any],
    *,
    estimated_tokens: int = 0,
    used_local_llm: bool = True,
) -> TextTaskClassification:
    """Parse Ollama/Claude JSON into a strict classification result."""

    raw = str(payload.get("complexity") or "").strip().lower()
    if raw in {"simple", "local", "easy", "routine"}:
        complexity = TextTaskComplexity.SIMPLE
    else:
        complexity = TextTaskComplexity.NEEDS_CLAUDE
    reason = str(payload.get("reason") or complexity.value).strip() or complexity.value
    return TextTaskClassification(
        complexity=complexity,
        reason=reason[:300],
        estimated_tokens=max(0, estimated_tokens),
        used_local_llm=used_local_llm,
    )


def text_classification_system_prompt() -> str:
    return (
        "You are a routing classifier for marketplace-card AI workloads. "
        "Decide if the task is SIMPLE (routine text / short reviews / JSON fix) "
        "or NEEDS_CLAUDE (ambiguous, long, multi-hop, or high-stakes reasoning). "
        "Never invent product facts. Reply with STRICT JSON only."
    )


def build_text_classification_prompt(
    *,
    kind: ReasoningTaskKind,
    text_preview: str,
    estimated_tokens: int,
    item_count: int = 0,
) -> str:
    preview = text_preview.strip()
    if len(preview) > 2_000:
        preview = preview[:2_000] + "…"
    return (
        f"task_kind={kind.value}\n"
        f"estimated_tokens={estimated_tokens}\n"
        f"item_count={item_count}\n"
        f"text_preview:\n{preview}\n\n"
        'Return JSON: {"complexity":"simple"|"needs_claude","reason":"..."}'
    )
