"""Smart Variant Sync domain: one product photo → N fabric color variants."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.bulk_generation import detect_image_mime
from app.domain.generation import GenerationJobStatus

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class VariantSyncStatus(StrEnum):
    """Lifecycle of a multi-color variant sync job."""

    QUEUED = "queued"
    RECOLORING = "recoloring"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class VariantItemStatus(StrEnum):
    """Lifecycle of one color variant inside a sync job."""

    PENDING = "pending"
    RECOLORING = "recoloring"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VariantNotifyChannel(StrEnum):
    """Delivery channels when the whole sync reaches a terminal state."""

    TELEGRAM = "telegram"
    PUSH = "push"


@dataclass(frozen=True, slots=True)
class ColorSpec:
    """One target fabric color requested by the seller."""

    name: str
    hex_code: str | None = None

    @property
    def slug(self) -> str:
        base = self.name.strip().lower()
        slug = _SLUG_RE.sub("-", base).strip("-")
        if self.hex_code:
            slug = f"{slug}-{self.hex_code.lstrip('#').lower()}" if slug else (
                self.hex_code.lstrip("#").lower()
            )
        return slug or "color"

    @property
    def display_label(self) -> str:
        if self.hex_code:
            return f"{self.name} ({self.normalize_hex()})"
        return self.name

    def normalize_hex(self) -> str | None:
        if self.hex_code is None:
            return None
        match = _HEX_RE.fullmatch(self.hex_code.strip())
        if match is None:
            return None
        return f"#{match.group(1).upper()}"


@dataclass(frozen=True, slots=True)
class VariantItemView:
    """Projection of one color variant item."""

    id: UUID
    sync_id: UUID
    position: int
    color_name: str
    color_hex: str | None
    color_slug: str
    status: VariantItemStatus
    recolored_object_key: str | None
    generation_job_id: UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class VariantSyncView:
    """Projection of a Smart Variant Sync aggregate."""

    id: UUID
    user_id: UUID
    status: VariantSyncStatus
    product_category: str | None
    engine_mode: str
    post_processing_mode: str
    apply_text_overlays: bool
    source_image_object_key: str
    source_mime_type: str
    total_items: int
    completed_items: int
    failed_items: int
    skipped_items: int
    notify_telegram: bool
    notify_push: bool
    telegram_notified_at: datetime | None
    push_notified_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: tuple[VariantItemView, ...] = ()


@dataclass(frozen=True, slots=True)
class VariantPushPayload:
    """Title/body/data delivered through the push (in-app) channel."""

    title: str
    body: str
    data: dict[str, str]


def _normalize_hex(raw: str) -> str:
    match = _HEX_RE.fullmatch(raw.strip())
    if match is None:
        raise ValueError(f"Invalid hex color: {raw!r}. Use #RRGGBB.")
    return f"#{match.group(1).upper()}"


def _color_from_mapping(raw: dict[str, object]) -> ColorSpec:
    name_val = raw.get("name") or raw.get("color") or raw.get("label")
    hex_val = raw.get("hex") or raw.get("hex_code") or raw.get("color_hex")
    if not isinstance(name_val, str) or not name_val.strip():
        raise ValueError("Each color object must include a non-empty 'name'.")
    name = name_val.strip()[:64]
    hex_code: str | None = None
    if hex_val is not None:
        if not isinstance(hex_val, str):
            raise ValueError("Color 'hex' must be a string like #RRGGBB.")
        hex_code = _normalize_hex(hex_val)
    elif _HEX_RE.fullmatch(name.lstrip("#")):
        hex_code = _normalize_hex(name)
        name = hex_code
    return ColorSpec(name=name, hex_code=hex_code)


def _color_from_token(token: str) -> ColorSpec:
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("Empty color token.")
    if "," in cleaned and cleaned.count(",") == 1:
        left, right = cleaned.split(",", 1)
        left, right = left.strip(), right.strip()
        if _HEX_RE.fullmatch(right.lstrip("#")) or right.startswith("#"):
            return ColorSpec(name=left[:64], hex_code=_normalize_hex(right))
    if _HEX_RE.fullmatch(cleaned.lstrip("#")):
        hex_code = _normalize_hex(cleaned)
        return ColorSpec(name=hex_code, hex_code=hex_code)
    return ColorSpec(name=cleaned[:64], hex_code=None)


def parse_color_specs(raw: str | list[object] | None, *, max_colors: int) -> tuple[ColorSpec, ...]:
    """Parse target colors from JSON array/objects or comma-separated names."""

    if max_colors <= 0:
        raise ValueError("max_colors must be positive.")
    if raw is None:
        raise ValueError("At least one target color is required.")

    items: list[object]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("At least one target color is required.")
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("colors JSON must be a valid array.") from exc
            if not isinstance(parsed, list):
                raise ValueError("colors JSON must be an array.")
            items = parsed
        else:
            items = [part.strip() for part in text.split(",") if part.strip()]
    else:
        raise ValueError("colors must be a JSON array or comma-separated string.")

    if not items:
        raise ValueError("At least one target color is required.")
    if len(items) > max_colors:
        raise ValueError(f"At most {max_colors} color variants are allowed.")

    colors: list[ColorSpec] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            color = _color_from_mapping(item)
        elif isinstance(item, str):
            color = _color_from_token(item)
        else:
            raise ValueError("Each color must be a string or {name, hex} object.")
        key = color.slug
        if key in seen:
            raise ValueError(f"Duplicate color variant: {color.display_label}.")
        seen.add(key)
        colors.append(color)
    return tuple(colors)


def validate_source_image(data: bytes, *, max_bytes: int) -> tuple[str, str]:
    """Return (mime, extension) for a JPEG/PNG/WebP source photo."""

    if not data:
        raise ValueError("Uploaded image is empty.")
    if len(data) > max_bytes:
        raise ValueError(f"Image exceeds the {max_bytes}-byte upload limit.")
    detected = detect_image_mime(data)
    if detected is None:
        raise ValueError("Source image must be JPEG, PNG, or WebP.")
    return detected


def build_recolor_prompt(color: ColorSpec, *, product_category: str | None = None) -> str:
    """Img2img instruction: change fabric color, keep texture/shadows/logos."""

    niche = (product_category or "apparel").strip() or "apparel"
    target = color.display_label
    return (
        f"Recolor only the garment fabric of this {niche} product photo to {target}. "
        "Preserve original fabric texture, weave, folds, seams, stitching, logos, "
        "prints, labels, shadows, highlights, and realistic lighting. "
        "Do not change the product shape, background, camera angle, or composition. "
        "Keep photorealistic marketplace catalog quality."
    )


def build_color_overlay_texts(color: ColorSpec) -> dict[str, str]:
    """Per-slide infographic copy tuned to the target color variant."""

    label = color.display_label
    return {
        "cover": f"Цвет: {label}",
        "lifestyle": f"Образ в цвете {label}",
        "technical": f"Вариант {label}",
        "trust": f"Доступен цвет {label}",
        "macro": f"Текстура · {label}",
    }


def map_job_status_to_item(status: GenerationJobStatus | str) -> VariantItemStatus:
    """Map a child generation job status onto a variant item status."""

    value = GenerationJobStatus(status) if isinstance(status, str) else status
    if value is GenerationJobStatus.COMPLETED:
        return VariantItemStatus.COMPLETED
    if value is GenerationJobStatus.FAILED:
        return VariantItemStatus.FAILED
    if value in (
        GenerationJobStatus.QUEUED,
        GenerationJobStatus.SUBMITTING,
    ):
        return VariantItemStatus.QUEUED
    return VariantItemStatus.RUNNING


def resolve_sync_terminal_status(
    *,
    total_items: int,
    completed_items: int,
    failed_items: int,
    skipped_items: int,
) -> VariantSyncStatus | None:
    """Return a terminal sync status when every color item is finished."""

    finished = completed_items + failed_items + skipped_items
    if total_items <= 0 or finished < total_items:
        return None
    if completed_items == 0:
        return VariantSyncStatus.FAILED
    if failed_items > 0 or skipped_items > 0:
        return VariantSyncStatus.PARTIAL
    return VariantSyncStatus.COMPLETED


def build_sync_ready_telegram_message(sync: VariantSyncView) -> str:
    """Human-readable Telegram copy when a color sync finishes."""

    status_label = {
        VariantSyncStatus.COMPLETED: "готова",
        VariantSyncStatus.PARTIAL: "частично готова",
        VariantSyncStatus.FAILED: "завершилась с ошибками",
    }.get(sync.status, "обработана")
    preset = sync.product_category or "default"
    return (
        f"🎨 Smart Variant Sync {status_label}!\n\n"
        f"Пресет: {preset}\n"
        f"Цветов успешно: {sync.completed_items}/{sync.total_items}\n"
        f"Ошибки: {sync.failed_items}\n"
        f"Пропущено: {sync.skipped_items}\n\n"
        f"Открой кабинет → Smart Variant Sync, job `{sync.id}`."
    )


def build_sync_ready_push_payload(sync: VariantSyncView) -> VariantPushPayload:
    """In-app / push payload when a color sync finishes."""

    status_label = {
        VariantSyncStatus.COMPLETED: "готова",
        VariantSyncStatus.PARTIAL: "частично готова",
        VariantSyncStatus.FAILED: "с ошибками",
    }.get(sync.status, "обработана")
    return VariantPushPayload(
        title="Цветовые варианты готовы",
        body=(
            f"Синхронизация {status_label}: "
            f"{sync.completed_items}/{sync.total_items} цветов."
        ),
        data={
            "type": "smart_variant_ready",
            "sync_id": str(sync.id),
            "status": sync.status.value,
        },
    )


def parse_notify_channels(raw: str | None) -> frozenset[VariantNotifyChannel]:
    """Parse comma-separated notify channels; default is telegram+push."""

    if raw is None or not raw.strip():
        return frozenset({VariantNotifyChannel.TELEGRAM, VariantNotifyChannel.PUSH})
    channels: set[VariantNotifyChannel] = set()
    for part in raw.split(","):
        token = part.strip().lower()
        if not token:
            continue
        try:
            channels.add(VariantNotifyChannel(token))
        except ValueError as exc:
            raise ValueError(
                "notify_channels must be a comma-separated list of "
                "'telegram' and/or 'push'."
            ) from exc
    if not channels:
        raise ValueError("At least one notify channel is required.")
    return frozenset(channels)
