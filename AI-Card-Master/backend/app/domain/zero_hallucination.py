"""Zero-Hallucination Cross-Check — OCR vs description dual verification (plan §57).

Pipeline:
1. Claude Vision extracts OCR claims from competitor card images.
2. Claims are cross-checked against the listing title/description/specs.
3. Contradictions → verdict «Аномалия»; advice reliability scored 0–100%.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for Zero-Hallucination payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class CrossCheckVerdict(StrEnum):
    """Outcome of OCR ↔ description dual verification."""

    VERIFIED = "verified"
    ANOMALY = "anomaly"
    INSUFFICIENT_DATA = "insufficient_data"


ClaimType = Literal[
    "material",
    "size",
    "offer",
    "spec",
    "warranty",
    "composition",
    "other",
]

ContradictionSeverity = Literal["hard", "soft"]

VERDICT_LABEL_RU: dict[CrossCheckVerdict, str] = {
    CrossCheckVerdict.VERIFIED: "Проверено",
    CrossCheckVerdict.ANOMALY: "Аномалия",
    CrossCheckVerdict.INSUFFICIENT_DATA: "Недостаточно данных",
}

# Deterministic scoring knobs (plan §57 — advice reliability 0–100%).
HARD_CONTRADICTION_PENALTY = 25.0
SOFT_CONTRADICTION_PENALTY = 10.0
SPARSE_OCR_PENALTY = 10.0
SHORT_DESCRIPTION_PENALTY = 15.0
ANOMALY_RELIABILITY_CAP = 55.0
MIN_DESCRIPTION_CHARS = 20
MIN_OCR_CLAIMS_FOR_VERIFIED = 1


class OcrClaim(StrictDomainModel):
    """One factual claim read from competitor card imagery (Vision OCR)."""

    claim_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=500)
    slide_index: int = Field(ge=0, le=20)
    claim_type: ClaimType = "other"
    confidence: float = Field(ge=0.0, le=1.0)


class ContradictionItem(StrictDomainModel):
    """OCR claim that conflicts with the listing text description/specs."""

    claim_id: str = Field(min_length=1, max_length=64)
    ocr_text: str = Field(min_length=1, max_length=500)
    description_evidence: str = Field(min_length=1, max_length=500)
    severity: ContradictionSeverity
    note: str = Field(min_length=1, max_length=500)


class ZeroHallucinationCrossCheck(StrictDomainModel):
    """Dual-check result: OCR claims vs description + advice reliability %."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    ocr_claims: list[OcrClaim] = Field(default_factory=list, max_length=40)
    contradictions: list[ContradictionItem] = Field(default_factory=list, max_length=40)
    supported_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    verdict: CrossCheckVerdict = CrossCheckVerdict.INSUFFICIENT_DATA
    verdict_label: str = Field(default="Недостаточно данных", min_length=1, max_length=64)
    advice_reliability_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_trace: str = Field(default="", max_length=4000)
    model_name: str = Field(default="", max_length=128)

    @field_validator("supported_claim_ids", mode="before")
    @classmethod
    def _clean_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("supported_claim_ids must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("supported_claim_ids items must be strings.")
            text = item.strip()
            if text:
                cleaned.append(text[:64])
        return cleaned

    @model_validator(mode="after")
    def _sync_verdict_label(self) -> ZeroHallucinationCrossCheck:
        expected = VERDICT_LABEL_RU[self.verdict]
        if self.verdict_label != expected:
            self.verdict_label = expected
        return self


class ClaudeCrossCheckPayload(StrictDomainModel):
    """Raw structured JSON from Claude Vision OCR ↔ description check."""

    ocr_claims: list[OcrClaim] = Field(default_factory=list, max_length=40)
    contradictions: list[ContradictionItem] = Field(default_factory=list, max_length=40)
    supported_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    model_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning_trace: str = Field(min_length=1, max_length=4000)

    @field_validator("supported_claim_ids", mode="before")
    @classmethod
    def _clean_ids(cls, value: object) -> list[str]:
        return ZeroHallucinationCrossCheck._clean_ids(value)


ZERO_HALLUCINATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ocr_claims",
        "contradictions",
        "supported_claim_ids",
        "model_confidence",
        "reasoning_trace",
    ],
    "properties": {
        "ocr_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_id",
                    "text",
                    "slide_index",
                    "claim_type",
                    "confidence",
                ],
                "properties": {
                    "claim_id": {"type": "string"},
                    "text": {"type": "string"},
                    "slide_index": {"type": "integer"},
                    "claim_type": {
                        "type": "string",
                        "enum": [
                            "material",
                            "size",
                            "offer",
                            "spec",
                            "warranty",
                            "composition",
                            "other",
                        ],
                    },
                    "confidence": {"type": "number"},
                },
            },
        },
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_id",
                    "ocr_text",
                    "description_evidence",
                    "severity",
                    "note",
                ],
                "properties": {
                    "claim_id": {"type": "string"},
                    "ocr_text": {"type": "string"},
                    "description_evidence": {"type": "string"},
                    "severity": {"type": "string", "enum": ["hard", "soft"]},
                    "note": {"type": "string"},
                },
            },
        },
        "supported_claim_ids": {"type": "array", "items": {"type": "string"}},
        "model_confidence": {"type": "number"},
        "reasoning_trace": {"type": "string"},
    },
}


_CROSS_CHECK_SYSTEM_PROMPT = (
    "You are a Zero-Hallucination auditor for Wildberries / Ozon product cards. "
    "You receive competitor card PHOTOS (Vision OCR) and the listing text "
    "(title, description, specs). "
    "Task: (1) Extract factual OCR claims visible on the images "
    "(materials, sizes, offers, warranties, composition badges). "
    "(2) Cross-check EACH claim against the provided text description/specs. "
    "(3) If OCR contradicts the description, list it in contradictions with "
    "severity=hard (direct conflict) or soft (ambiguous / incomplete match). "
    "Return ONLY valid JSON matching the schema. "
    "ANTI-HALLUCINATION (CRITICAL): NEVER invent OCR text that is not visible. "
    "NEVER invent description quotes that are absent from the input. "
    "If images have no readable text or description is empty, return empty "
    "ocr_claims/contradictions and explain in reasoning_trace. "
    "Put intermediate reasoning into reasoning_trace."
)


def cross_check_system_prompt() -> str:
    return _CROSS_CHECK_SYSTEM_PROMPT


def build_cross_check_user_prompt(
    *,
    title: str | None,
    description: str | None,
    specs: list[str],
    image_count: int,
    marketplace: str | None = None,
    article: str | None = None,
) -> str:
    """User prompt: listing text context; Vision images already attached."""

    payload = {
        "article": (article or "").strip() or None,
        "marketplace": (marketplace or "").strip() or None,
        "title": (title or "").strip() or None,
        "description": (description or "")[:6000],
        "specs": specs[:40],
        "images_attached": image_count,
    }
    return (
        "Zero-Hallucination Cross-Check (двойная проверка).\n"
        "Сверь OCR-данные с картинок конкурента с его текстовым описанием.\n"
        "Если найдены противоречия — перечисли их в contradictions "
        "(severity=hard|soft).\n"
        "Сначала reasoning_trace, затем строго JSON по схеме.\n"
        f"Входные текстовые данные:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def count_contradictions_by_severity(
    contradictions: list[ContradictionItem],
) -> tuple[int, int]:
    """Return (hard_count, soft_count)."""

    hard = sum(1 for item in contradictions if item.severity == "hard")
    soft = sum(1 for item in contradictions if item.severity == "soft")
    return hard, soft


def compute_advice_reliability_pct(
    *,
    ocr_claim_count: int,
    hard_contradictions: int,
    soft_contradictions: int,
    description_chars: int,
    model_confidence: float | None = None,
) -> tuple[float, CrossCheckVerdict]:
    """Deterministic 0–100% advice reliability + verdict from dual-check facts.

    Contradictions force verdict «Аномалия» and cap reliability.
    Sparse OCR/description → «Недостаточно данных» with low score.
    """

    if ocr_claim_count < MIN_OCR_CLAIMS_FOR_VERIFIED or description_chars < MIN_DESCRIPTION_CHARS:
        if ocr_claim_count == 0 and description_chars < MIN_DESCRIPTION_CHARS:
            return 0.0, CrossCheckVerdict.INSUFFICIENT_DATA
        base = 15.0 if ocr_claim_count or description_chars else 0.0
        if model_confidence is not None:
            base = min(base, model_confidence * 30.0)
        return _clamp_pct(base), CrossCheckVerdict.INSUFFICIENT_DATA

    score = 100.0
    score -= hard_contradictions * HARD_CONTRADICTION_PENALTY
    score -= soft_contradictions * SOFT_CONTRADICTION_PENALTY
    if ocr_claim_count < 2:
        score -= SPARSE_OCR_PENALTY
    if description_chars < 80:
        score -= SHORT_DESCRIPTION_PENALTY

    if model_confidence is not None:
        conf = max(0.0, min(1.0, model_confidence))
        score = 0.7 * score + 0.3 * (conf * 100.0)

    score = _clamp_pct(score)

    is_anomaly = hard_contradictions > 0 or soft_contradictions >= 2
    if is_anomaly:
        score = min(score, ANOMALY_RELIABILITY_CAP)
        return score, CrossCheckVerdict.ANOMALY
    return score, CrossCheckVerdict.VERIFIED


def finalize_cross_check(
    payload: ClaudeCrossCheckPayload,
    *,
    description: str | None,
    model_name: str,
) -> ZeroHallucinationCrossCheck:
    """Apply deterministic verdict + reliability % on top of Claude JSON."""

    hard, soft = count_contradictions_by_severity(payload.contradictions)
    reliability, verdict = compute_advice_reliability_pct(
        ocr_claim_count=len(payload.ocr_claims),
        hard_contradictions=hard,
        soft_contradictions=soft,
        description_chars=len((description or "").strip()),
        model_confidence=payload.model_confidence,
    )
    # Claude found contradictions → always mark Аномалия even if scoring
    # would have been soft-only borderline.
    if payload.contradictions and verdict is CrossCheckVerdict.VERIFIED:
        if hard > 0 or soft >= 1:
            verdict = CrossCheckVerdict.ANOMALY
            reliability = min(reliability, ANOMALY_RELIABILITY_CAP)

    return ZeroHallucinationCrossCheck(
        ocr_claims=list(payload.ocr_claims),
        contradictions=list(payload.contradictions),
        supported_claim_ids=list(payload.supported_claim_ids),
        verdict=verdict,
        verdict_label=VERDICT_LABEL_RU[verdict],
        advice_reliability_pct=reliability,
        model_confidence=payload.model_confidence,
        reasoning_trace=payload.reasoning_trace[:4000],
        model_name=model_name.strip()[:128],
    )


def build_insufficient_cross_check(
    *,
    reason: str,
    model_name: str = "",
) -> ZeroHallucinationCrossCheck:
    """Safe payload when Vision OCR or description cannot be dual-checked."""

    return ZeroHallucinationCrossCheck(
        ocr_claims=[],
        contradictions=[],
        supported_claim_ids=[],
        verdict=CrossCheckVerdict.INSUFFICIENT_DATA,
        verdict_label=VERDICT_LABEL_RU[CrossCheckVerdict.INSUFFICIENT_DATA],
        advice_reliability_pct=0.0,
        model_confidence=0.0,
        reasoning_trace=reason[:4000],
        model_name=model_name.strip()[:128],
    )


def reliability_pct_from_confidence(confidence: float) -> float:
    """Map 0–1 model confidence onto advice reliability 0–100%."""

    return _clamp_pct(max(0.0, min(1.0, confidence)) * 100.0)


def attach_reliability_to_advice(
    *,
    base_confidence: float,
    cross_check: ZeroHallucinationCrossCheck | None,
) -> float:
    """Blend strategy confidence with OCR cross-check for advice %.

    When cross-check is an anomaly, reliability is capped by the dual-check score.
    """

    from_confidence = reliability_pct_from_confidence(base_confidence)
    if cross_check is None:
        return from_confidence
    if cross_check.verdict is CrossCheckVerdict.INSUFFICIENT_DATA:
        return _clamp_pct(min(from_confidence, 40.0))
    if cross_check.verdict is CrossCheckVerdict.ANOMALY:
        return _clamp_pct(min(from_confidence, cross_check.advice_reliability_pct))
    # Verified: slight boost toward the dual-check score.
    return _clamp_pct(0.6 * from_confidence + 0.4 * cross_check.advice_reliability_pct)


def dump_cross_check(result: ZeroHallucinationCrossCheck) -> dict[str, Any]:
    return result.model_dump(mode="json")


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
        raise ValueError("Claude response JSON root must be an object.")
    return payload


def _clamp_pct(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 1)
