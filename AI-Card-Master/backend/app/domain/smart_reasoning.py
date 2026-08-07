"""Smart Reasoning Routing & Caching — cost-aware Claude model selection.

Plan §55: simple analytics → Claude 3.5 Haiku; deep «Глаз Бога» (and other
Vision-heavy analysis) → Claude 4.7 Opus. Content-addressed Redis analytics
cache (24h) avoids repeat API spend on identical inputs.

Cost audit C1/C2: DEEP is reserved for Eye of God / Visual / Competitor Vision
(and CoT Vision). Text-only cards (has_vision=False) downgrade DEEP → SIMPLE.
ZERO_HALLUCINATION and EXPORT_FAIL_SAFE_FIX use Haiku + JSON schema.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Mapping


class ReasoningTier(StrEnum):
    """Cost tier for model calls (plan §55 + §69 LOCAL)."""

    SIMPLE = "simple"
    DEEP = "deep"
    LOCAL = "local"


class ReasoningTaskKind(StrEnum):
    """Named Claude analytics workloads used by composition roots."""

    PAIN_ANALYSIS = "pain_analysis"
    ORACLE_ENRICHMENT = "oracle_enrichment"
    AB_HYPOTHESES = "ab_hypotheses"
    AI_STRATEGY = "ai_strategy"
    EYE_OF_GOD = "eye_of_god"
    VISUAL_AUDIT = "visual_audit"
    COMPETITOR_AUDIT = "competitor_audit"
    CLAUDE_REASONING = "claude_reasoning"
    ZERO_HALLUCINATION = "zero_hallucination"
    EXPORT_FAIL_SAFE_FIX = "export_fail_safe_fix"
    # Plan §69 — routine text workloads for local LLM (Ollama) routing.
    TEXT_CLASSIFICATION = "text_classification"
    SEMANTIC_COMPRESSION = "semantic_compression"


# Vision-heavy workloads that stay on Opus when photos are present.
# Without images they downgrade to SIMPLE (Haiku) — cost audit C1.
_VISION_DEEP_KINDS: frozenset[ReasoningTaskKind] = frozenset(
    {
        ReasoningTaskKind.EYE_OF_GOD,
        ReasoningTaskKind.VISUAL_AUDIT,
        ReasoningTaskKind.COMPETITOR_AUDIT,
        ReasoningTaskKind.CLAUDE_REASONING,
    }
)

# Simple text/enrichment / JSON-schema fixes → Haiku; deep Vision → Opus.
# LOCAL tasks → Ollama (Llama 3) when Token Governor enables local routing.
# ZERO_HALLUCINATION + EXPORT_FAIL_SAFE_FIX: Haiku/Sonnet JSON (cost audit C2).
_TASK_TIERS: Mapping[ReasoningTaskKind, ReasoningTier] = {
    ReasoningTaskKind.PAIN_ANALYSIS: ReasoningTier.SIMPLE,
    ReasoningTaskKind.ORACLE_ENRICHMENT: ReasoningTier.SIMPLE,
    ReasoningTaskKind.AB_HYPOTHESES: ReasoningTier.SIMPLE,
    ReasoningTaskKind.AI_STRATEGY: ReasoningTier.SIMPLE,
    ReasoningTaskKind.TEXT_CLASSIFICATION: ReasoningTier.LOCAL,
    ReasoningTaskKind.SEMANTIC_COMPRESSION: ReasoningTier.LOCAL,
    ReasoningTaskKind.EYE_OF_GOD: ReasoningTier.DEEP,
    ReasoningTaskKind.VISUAL_AUDIT: ReasoningTier.DEEP,
    ReasoningTaskKind.COMPETITOR_AUDIT: ReasoningTier.DEEP,
    ReasoningTaskKind.CLAUDE_REASONING: ReasoningTier.DEEP,
    ReasoningTaskKind.ZERO_HALLUCINATION: ReasoningTier.SIMPLE,
    ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX: ReasoningTier.SIMPLE,
}


def tier_for_task(
    kind: ReasoningTaskKind,
    *,
    has_vision: bool = True,
) -> ReasoningTier:
    """Return the cost tier for a named analytics workload.

    When ``has_vision=False``, Vision-locked DEEP kinds downgrade to SIMPLE
    so text-only competitor/CoT cards do not burn Opus credits (C1).
    """

    base = _TASK_TIERS[kind]
    if base is ReasoningTier.DEEP and not has_vision and kind in _VISION_DEEP_KINDS:
        return ReasoningTier.SIMPLE
    return base


def model_for_task(
    kind: ReasoningTaskKind,
    *,
    simple_model: str,
    deep_model: str,
    local_model: str | None = None,
    has_vision: bool = True,
) -> str:
    """Select model id for the workload (Haiku / Opus / Ollama)."""

    simple = simple_model.strip()
    deep = deep_model.strip()
    if not simple:
        raise ValueError("simple_model must not be empty.")
    if not deep:
        raise ValueError("deep_model must not be empty.")
    tier = tier_for_task(kind, has_vision=has_vision)
    if tier is ReasoningTier.DEEP:
        return deep
    if tier is ReasoningTier.LOCAL:
        local = (local_model or "").strip()
        if not local:
            raise ValueError("local_model must not be empty for LOCAL tier tasks.")
        return local
    return simple


def model_supports_adaptive_thinking(model_name: str) -> bool:
    """Opus/Sonnet 4.x support adaptive thinking + output_config.effort."""

    normalized = model_name.strip().lower()
    if not normalized:
        return False
    if "haiku" in normalized:
        return False
    return (
        "opus-4" in normalized
        or "sonnet-4" in normalized
        or normalized.startswith("claude-opus-4")
        or normalized.startswith("claude-sonnet-4")
        or "claude-4" in normalized
    )


def canonical_json_bytes(payload: Any) -> bytes:
    """Stable UTF-8 JSON for fingerprints (sorted keys, compact)."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def analytics_fingerprint(*parts: Any) -> str:
    """SHA-256 fingerprint over one or more canonical payload parts."""

    digest = hashlib.sha256()
    for part in parts:
        digest.update(canonical_json_bytes(part))
        digest.update(b"\0")
    return digest.hexdigest()


def redis_analytics_key(
    *,
    task_kind: str,
    model_name: str,
    fingerprint: str,
    version: str = "v1",
) -> str:
    """Content-addressed Redis key for a cached Claude analytics result."""

    kind = task_kind.strip().lower() or "unknown"
    model = model_name.strip().lower() or "unknown"
    fp = fingerprint.strip().lower()
    if len(fp) < 16:
        raise ValueError("fingerprint must be a content hash.")
    ver = version.strip() or "v1"
    return f"claude:analytics:{ver}:{kind}:{model}:{fp}"


def fingerprint_messages_request(
    *,
    model_name: str,
    system: str,
    content: list[dict[str, Any]],
    json_schema: Mapping[str, Any] | None = None,
    operation: str | None = None,
) -> str:
    """Fingerprint a Claude messages call (hashes image payloads)."""

    normalized_content: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            normalized_content.append(
                {"type": "text", "text": str(block.get("text") or "")}
            )
            continue
        if block_type == "image":
            source = block.get("source")
            data = ""
            media_type = ""
            if isinstance(source, dict):
                data = str(source.get("data") or "")
                media_type = str(source.get("media_type") or "")
            # Hash image bytes (base64) so keys stay short and stable.
            data_hash = hashlib.sha256(data.encode("ascii", errors="ignore")).hexdigest()
            normalized_content.append(
                {
                    "type": "image",
                    "media_type": media_type,
                    "data_sha256": data_hash,
                }
            )
            continue
        normalized_content.append({"type": str(block_type), "raw": block})

    return analytics_fingerprint(
        {
            "model": model_name.strip(),
            "system": system,
            "content": normalized_content,
            "schema": dict(json_schema) if json_schema is not None else None,
            "operation": operation,
        }
    )
