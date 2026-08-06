"""Ports for Smart Variant Sync persistence, recolor, and push delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)
from app.domain.smart_variant import (
    ColorSpec,
    VariantItemStatus,
    VariantItemView,
    VariantPushPayload,
    VariantSyncStatus,
    VariantSyncView,
)


class SmartVariantPersistencePort(Protocol):
    """Storage operations for color-variant sync jobs and items."""

    async def find_idempotent_sync(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VariantSyncView | None:
        """Return an existing sync created with the same idempotency key."""

    async def create_sync(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_image_object_key: str,
        source_mime_type: str,
        colors: tuple[ColorSpec, ...],
        notify_telegram: bool,
        notify_push: bool,
    ) -> VariantSyncView:
        """Persist a queued sync with pending color items."""

    async def get_sync_for_user(
        self, *, user_id: UUID, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        """Load one sync owned by the user."""

    async def get_sync(
        self, *, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        """Load a sync by id (worker path)."""

    async def mark_sync_status(
        self,
        *,
        sync_id: UUID,
        status: VariantSyncStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> VariantSyncView:
        """Update aggregate sync status / counters."""

    async def mark_item_recoloring(self, *, item_id: UUID) -> VariantItemView:
        """Mark a color item as currently being recolored."""

    async def mark_item_recolored(
        self,
        *,
        item_id: UUID,
        recolored_object_key: str,
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        """Attach recolored S3 input key to an item."""

    async def mark_item_job(
        self,
        *,
        item_id: UUID,
        generation_job_id: UUID,
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        """Link a created GenerationJob to the variant item."""

    async def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_message: str,
        status: VariantItemStatus = VariantItemStatus.FAILED,
    ) -> VariantItemView:
        """Mark a single color item as failed/skipped."""

    async def list_active_sync_ids(self, *, limit: int) -> tuple[UUID, ...]:
        """Syncs in recoloring/running that need completion polling."""

    async def sync_item_statuses_from_jobs(self, *, sync_id: UUID) -> VariantSyncView:
        """Refresh item statuses from linked generation jobs and recompute counters."""

    async def mark_notified(
        self,
        *,
        sync_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> VariantSyncView:
        """Record that completion notifications were delivered."""

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        """Return linked Telegram chat id, if any."""

    async def get_job_status(self, job_id: UUID) -> GenerationJobStatus | None:
        """Lookup child generation job status."""


class FabricRecolorPort(Protocol):
    """AI fabric recolor while preserving texture and shadows."""

    async def recolor_fabric(
        self,
        *,
        source_image: bytes,
        color: ColorSpec,
        product_category: str | None,
    ) -> bytes:
        """Return recolored product image bytes."""


class VariantPushNotifierPort(Protocol):
    """Deliver an in-app / push notification to a user."""

    async def send(
        self,
        *,
        user_id: UUID,
        payload: VariantPushPayload,
    ) -> bool:
        """Return True when the notification was accepted for delivery."""
