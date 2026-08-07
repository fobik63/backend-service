"""Custom Brand LoRA domain: reference set → personal style filter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.bulk_generation import detect_image_mime

_TRIGGER_RE = re.compile(r"[^a-z0-9]+")
_BRAND_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 ._&\-]{1,63}$")


class BrandLoraStatus(StrEnum):
    """Lifecycle of a brand style training profile."""

    DRAFT = "draft"
    QUEUED = "queued"
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class BrandLoraReferenceView:
    """One uploaded brand reference photo."""

    id: UUID
    profile_id: UUID
    position: int
    object_key: str
    mime_type: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BrandLoraView:
    """Projection of a Custom Brand LoRA profile."""

    id: UUID
    user_id: UUID
    name: str
    trigger_word: str
    status: BrandLoraStatus
    is_active: bool
    brand_style_prompt: str | None
    lora_weights_url: str | None
    provider_training_id: str | None
    provider_version_id: str | None
    lora_scale: float
    reference_count: int
    coins_charged: int
    error_message: str | None
    training_progress: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    trained_at: datetime | None
    references: tuple[BrandLoraReferenceView, ...] = ()


@dataclass(frozen=True, slots=True)
class BrandStyleFilter:
    """Active filter applied to every generation for a brand user."""

    profile_id: UUID
    trigger_word: str
    brand_style_prompt: str
    lora_weights_url: str | None
    lora_scale: float


@dataclass(frozen=True, slots=True)
class LoraTrainingStartResult:
    """Provider acknowledgement after kicking off LoRA training."""

    training_id: str
    status: str


@dataclass(frozen=True, slots=True)
class LoraTrainingPollResult:
    """Provider snapshot while LoRA training is in flight or finished."""

    training_id: str
    status: str
    progress: int
    weights_url: str | None
    version_id: str | None
    error_message: str | None
    brand_style_prompt: str | None = None


def normalize_brand_name(name: str) -> str:
    """Trim and validate a human-facing brand profile name."""

    cleaned = " ".join(name.strip().split())
    if not cleaned or not _BRAND_NAME_RE.fullmatch(cleaned):
        raise ValueError(
            "Brand name must be 2–64 chars (letters, digits, spaces, ._-&)."
        )
    return cleaned


def build_trigger_word(brand_name: str) -> str:
    """Stable LoRA trigger token derived from the brand name."""

    ascii_ish = (
        brand_name.lower()
        .replace("ё", "e")
        .replace("й", "i")
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = _TRIGGER_RE.sub("", ascii_ish)
    if len(slug) < 3:
        slug = f"brand{abs(hash(brand_name)) % 10_000:04d}"
    return f"brnd{slug[:24]}"


def validate_reference_image(data: bytes, *, max_bytes: int) -> tuple[str, str]:
    """Validate one brand reference photo; return (mime, extension)."""

    if not data:
        raise ValueError("Reference image is empty.")
    if len(data) > max_bytes:
        raise ValueError(f"Reference image exceeds the {max_bytes}-byte limit.")
    detected = detect_image_mime(data)
    if detected is None:
        raise ValueError("Reference image must be JPEG, PNG, or WebP.")
    return detected


def validate_reference_batch_count(
    count: int, *, min_images: int, max_images: int
) -> None:
    """Enforce the 20–30 reference photo contract for LoRA quality."""

    if count < min_images:
        raise ValueError(
            f"Upload at least {min_images} brand reference photos "
            f"(received {count})."
        )
    if count > max_images:
        raise ValueError(
            f"Upload at most {max_images} brand reference photos "
            f"(received {count})."
        )


def synthesize_brand_style_prompt(
    *,
    brand_name: str,
    trigger_word: str,
    notes: str | None = None,
) -> str:
    """Build Midjourney/SD-compatible brand DNA when weight training is offline."""

    parts = [
        f"consistent brand identity of {brand_name}",
        f"trained style token {trigger_word}",
        "cohesive color palette, typography rhythm, lighting mood",
        "marketplace card aesthetics matching seller brandbook",
        "no competing visual languages, preserve product fidelity",
    ]
    if notes and notes.strip():
        parts.append(f"brand notes: {notes.strip()[:400]}")
    return ", ".join(parts)


def apply_brand_filter_to_style(selected_style: str, brand: BrandStyleFilter) -> str:
    """Append brand DNA to the selected style descriptor."""

    base = selected_style.strip()
    prompt = brand.brand_style_prompt.strip()
    suffix = f"{brand.trigger_word}, {prompt}" if prompt else brand.trigger_word
    # Empty prompt must NOT use ``"" in base`` (always True in Python).
    prompt_token = prompt[:40] if prompt else None
    if brand.trigger_word in base and (
        prompt_token is None or prompt_token in base
    ):
        return base
    merged = f"{base}, {suffix}" if base else suffix
    return merged[:500]


def apply_brand_filter_to_prompt(prompt: str, brand: BrandStyleFilter) -> str:
    """Inject the personal LoRA / BrandDNA context into the generation prompt."""

    base = prompt.strip()
    parts = [
        f"[Brand LoRA:{brand.trigger_word}] {brand.brand_style_prompt.strip()}".strip()
    ]
    if brand.lora_weights_url:
        # Stable Diffusion / Comfy-compatible LoRA reference consumed by ai_engine.
        parts.append(
            f"<lora:{brand.lora_weights_url}:{brand.lora_scale:.2f}>"
        )
    injection = " ".join(p for p in parts if p).strip()
    if injection and injection in base:
        return base
    merged = f"{base}\n{injection}".strip() if base else injection
    return merged[:4000]


def is_terminal_status(status: BrandLoraStatus) -> bool:
    """Whether the profile no longer needs worker polling."""

    return status in {
        BrandLoraStatus.READY,
        BrandLoraStatus.FAILED,
        BrandLoraStatus.ARCHIVED,
    }


def map_provider_status(raw: str) -> BrandLoraStatus:
    """Map Replicate/provider job status strings onto domain statuses."""

    normalised = raw.strip().lower()
    if normalised in {"starting", "queued", "pending", "created"}:
        return BrandLoraStatus.QUEUED
    if normalised in {"processing", "running", "training", "in_progress"}:
        return BrandLoraStatus.TRAINING
    if normalised in {"succeeded", "success", "completed", "ready", "done"}:
        return BrandLoraStatus.READY
    if normalised in {"failed", "canceled", "cancelled", "error", "aborted"}:
        return BrandLoraStatus.FAILED
    return BrandLoraStatus.TRAINING
