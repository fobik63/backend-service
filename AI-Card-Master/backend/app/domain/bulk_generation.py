"""Bulk Generation domain: ZIP batch of products processed by one preset."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.generation import GenerationJobStatus

_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_SKIP_NAME_MARKERS = ("__macosx", ".ds_store", "thumbs.db")


class BulkBatchStatus(StrEnum):
    """Lifecycle of a multi-product generation batch."""

    QUEUED = "queued"
    UNPACKING = "unpacking"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class BulkItemStatus(StrEnum):
    """Lifecycle of one product inside a bulk batch."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BulkNotifyChannel(StrEnum):
    """Delivery channels when the whole batch reaches a terminal state."""

    TELEGRAM = "telegram"
    PUSH = "push"


@dataclass(frozen=True, slots=True)
class ExtractedProductImage:
    """One product image extracted from an uploaded ZIP archive."""

    product_key: str
    source_path: str
    data: bytes
    mime_type: str
    extension: str


@dataclass(frozen=True, slots=True)
class BulkItemView:
    """Projection of one bulk batch item."""

    id: UUID
    batch_id: UUID
    position: int
    product_key: str
    source_path: str
    status: BulkItemStatus
    input_object_key: str | None
    generation_job_id: UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BulkBatchView:
    """Projection of a bulk generation batch aggregate."""

    id: UUID
    user_id: UUID
    status: BulkBatchStatus
    product_category: str | None
    engine_mode: str
    post_processing_mode: str
    apply_text_overlays: bool
    source_zip_object_key: str
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
    items: tuple[BulkItemView, ...] = ()


@dataclass(frozen=True, slots=True)
class PushNotificationPayload:
    """Title/body/data delivered through the push (in-app) channel."""

    title: str
    body: str
    data: dict[str, str]


def _is_junk_path(path: str) -> bool:
    normalised = path.replace("\\", "/").strip("/")
    if not normalised or normalised.endswith("/"):
        return True
    lowered = normalised.lower()
    parts = lowered.split("/")
    if any(part.startswith(".") for part in parts):
        return True
    return any(marker in lowered for marker in _SKIP_NAME_MARKERS)


def _extension_of(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return f".{name.rsplit('.', 1)[-1].lower()}"


def detect_image_mime(data: bytes) -> tuple[str, str] | None:
    """Return (mime, extension) when bytes look like JPEG/PNG/WebP."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _product_key_for_member(path: str) -> str:
    normalised = path.replace("\\", "/").strip("/")
    parts = normalised.split("/")
    if len(parts) == 1:
        stem = parts[0]
        if "." in stem:
            return stem.rsplit(".", 1)[0] or stem
        return stem
    return parts[0]


def extract_products_from_zip(
    zip_bytes: bytes,
    *,
    max_products: int,
    max_image_bytes: int,
) -> tuple[ExtractedProductImage, ...]:
    """Unpack up to ``max_products`` product images from a ZIP archive.

    Supports flat files (``sku.jpg``) and one-level folders
    (``sku/photo.png`` — first valid image wins per folder).
    """

    if max_products <= 0:
        raise ValueError("max_products must be positive.")
    if not zip_bytes:
        raise ValueError("ZIP archive is empty.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive.") from exc

    # product_key → best candidate (first by sorted path)
    chosen: dict[str, ExtractedProductImage] = {}
    with archive:
        members = sorted(
            (info for info in archive.infolist() if not info.is_dir()),
            key=lambda info: info.filename.replace("\\", "/").lower(),
        )
        for info in members:
            path = info.filename.replace("\\", "/")
            if _is_junk_path(path):
                continue
            extension = _extension_of(path)
            if extension not in _IMAGE_EXTENSIONS:
                continue
            if info.file_size > max_image_bytes:
                continue
            try:
                data = archive.read(info)
            except Exception:
                continue
            if len(data) == 0 or len(data) > max_image_bytes:
                continue
            detected = detect_image_mime(data)
            if detected is None:
                continue
            mime_type, canonical_ext = detected
            product_key = _product_key_for_member(path)
            if product_key in chosen:
                continue
            chosen[product_key] = ExtractedProductImage(
                product_key=product_key,
                source_path=path,
                data=data,
                mime_type=mime_type,
                extension=canonical_ext,
            )
            if len(chosen) >= max_products:
                break

    products = tuple(chosen.values())
    if not products:
        raise ValueError(
            "ZIP must contain at least one JPEG, PNG, or WebP product image."
        )
    return products


def map_job_status_to_item(status: GenerationJobStatus | str) -> BulkItemStatus:
    """Map a child generation job status onto a bulk item status."""

    value = GenerationJobStatus(status) if isinstance(status, str) else status
    if value is GenerationJobStatus.COMPLETED:
        return BulkItemStatus.COMPLETED
    if value is GenerationJobStatus.FAILED:
        return BulkItemStatus.FAILED
    if value in (
        GenerationJobStatus.QUEUED,
        GenerationJobStatus.SUBMITTING,
    ):
        return BulkItemStatus.QUEUED
    return BulkItemStatus.RUNNING


def resolve_batch_terminal_status(
    *,
    total_items: int,
    completed_items: int,
    failed_items: int,
    skipped_items: int,
) -> BulkBatchStatus | None:
    """Return a terminal batch status when every item is finished, else None."""

    finished = completed_items + failed_items + skipped_items
    if total_items <= 0 or finished < total_items:
        return None
    if completed_items == 0:
        return BulkBatchStatus.FAILED
    if failed_items > 0 or skipped_items > 0:
        return BulkBatchStatus.PARTIAL
    return BulkBatchStatus.COMPLETED


def build_batch_ready_telegram_message(batch: BulkBatchView) -> str:
    """Human-readable Telegram copy when a bulk batch finishes."""

    status_label = {
        BulkBatchStatus.COMPLETED: "готова",
        BulkBatchStatus.PARTIAL: "частично готова",
        BulkBatchStatus.FAILED: "завершилась с ошибками",
    }.get(batch.status, "обработана")
    preset = batch.product_category or "default"
    return (
        f"📦 Массовая генерация {status_label}!\n\n"
        f"Пресет: {preset}\n"
        f"Успешно: {batch.completed_items}/{batch.total_items}\n"
        f"Ошибки: {batch.failed_items}\n"
        f"Пропущено: {batch.skipped_items}\n\n"
        f"Открой кабинет → Bulk Generation, batch `{batch.id}`."
    )


def build_batch_ready_push_payload(batch: BulkBatchView) -> PushNotificationPayload:
    """In-app / push payload when a bulk batch finishes."""

    status_label = {
        BulkBatchStatus.COMPLETED: "готова",
        BulkBatchStatus.PARTIAL: "частично готова",
        BulkBatchStatus.FAILED: "с ошибками",
    }.get(batch.status, "обработана")
    return PushNotificationPayload(
        title="Массовая генерация завершена",
        body=(
            f"Партия {status_label}: "
            f"{batch.completed_items}/{batch.total_items} успешно."
        ),
        data={
            "type": "bulk_generation_ready",
            "batch_id": str(batch.id),
            "status": batch.status.value,
        },
    )


def parse_notify_channels(raw: str | None) -> frozenset[BulkNotifyChannel]:
    """Parse comma-separated notify channels; default is telegram+push."""

    if raw is None or not raw.strip():
        return frozenset({BulkNotifyChannel.TELEGRAM, BulkNotifyChannel.PUSH})
    channels: set[BulkNotifyChannel] = set()
    for part in raw.split(","):
        token = part.strip().lower()
        if not token:
            continue
        try:
            channels.add(BulkNotifyChannel(token))
        except ValueError as exc:
            raise ValueError(
                "notify_channels must be a comma-separated list of "
                "'telegram' and/or 'push'."
            ) from exc
    if not channels:
        raise ValueError("At least one notify channel is required.")
    return frozenset(channels)
