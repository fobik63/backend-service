"""Ports for Bulk Generation persistence, storage helpers, and push delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.bulk_generation import (
    BulkBatchStatus,
    BulkBatchView,
    BulkItemStatus,
    BulkItemView,
    PushNotificationPayload,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)


class BulkGenerationPersistencePort(Protocol):
    """Storage operations for bulk batches and their product items."""

    async def find_idempotent_batch(
        self, *, user_id: UUID, idempotency_key: str
    ) -> BulkBatchView | None:
        """Return an existing batch created with the same idempotency key."""

    async def create_batch(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_zip_object_key: str,
        notify_telegram: bool,
        notify_push: bool,
    ) -> BulkBatchView:
        """Persist a queued batch waiting for ZIP unpack."""

    async def get_batch_for_user(
        self, *, user_id: UUID, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        """Load one batch owned by the user."""

    async def get_batch(
        self, *, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        """Load a batch by id (worker path)."""

    async def mark_batch_status(
        self,
        *,
        batch_id: UUID,
        status: BulkBatchStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> BulkBatchView:
        """Update aggregate batch status / counters."""

    async def replace_pending_items(
        self,
        *,
        batch_id: UUID,
        items: tuple[tuple[int, str, str], ...],
    ) -> tuple[BulkItemView, ...]:
        """Replace item rows with (position, product_key, source_path) pending stubs."""

    async def mark_item_input(
        self,
        *,
        item_id: UUID,
        input_object_key: str,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        """Attach uploaded S3 input key to an item."""

    async def mark_item_job(
        self,
        *,
        item_id: UUID,
        generation_job_id: UUID,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        """Link a created GenerationJob to the bulk item."""

    async def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_message: str,
        status: BulkItemStatus = BulkItemStatus.FAILED,
    ) -> BulkItemView:
        """Mark a single product item as failed/skipped."""

    async def list_active_batch_ids(self, *, limit: int) -> tuple[UUID, ...]:
        """Batches in unpacking/running that need completion polling."""

    async def sync_item_statuses_from_jobs(self, *, batch_id: UUID) -> BulkBatchView:
        """Refresh item statuses from linked generation jobs and recompute counters."""

    async def mark_notified(
        self,
        *,
        batch_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> BulkBatchView:
        """Record that completion notifications were delivered."""

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        """Return linked Telegram chat id, if any."""

    async def get_job_status(self, job_id: UUID) -> GenerationJobStatus | None:
        """Lookup child generation job status."""


class PushNotifierPort(Protocol):
    """Deliver an in-app / push notification to a user."""

    async def send(
        self,
        *,
        user_id: UUID,
        payload: PushNotificationPayload,
    ) -> bool:
        """Return True when the notification was accepted for delivery."""
