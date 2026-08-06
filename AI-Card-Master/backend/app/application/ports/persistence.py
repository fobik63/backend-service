"""Persistence and storage ports for generation application use cases."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.generation import (
    AttemptWorkItem,
    GenerationErrorInfo,
    GenerationJobStatus,
    GenerationWorkItem,
    MarketplaceTextContent,
    OutboxEventType,
    OutboxMessage,
    ProviderSubmission,
    ProviderWebhookEvent,
)


class GenerationRepositoryPort(Protocol):
    """Operations needed by use cases without exposing SQLAlchemy entities."""

    async def get_work_item(self, job_id: UUID) -> GenerationWorkItem | None: ...

    async def set_job_status(
        self,
        job_id: UUID,
        status: GenerationJobStatus,
        *,
        progress: int | None = None,
        provider_used: str | None = None,
        warning: str | None = None,
    ) -> None: ...

    async def begin_attempt(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        reply_ref: str,
    ) -> AttemptWorkItem: ...

    async def mark_attempt_submitted(
        self,
        attempt_id: UUID,
        submission: ProviderSubmission,
    ) -> None: ...

    async def mark_attempt_failed(
        self,
        attempt_id: UUID,
        message: str,
        *,
        abandoned: bool,
    ) -> None: ...

    async def get_attempt_by_reply_ref(
        self, reply_ref: str
    ) -> AttemptWorkItem | None: ...

    async def get_attempted_providers(self, slide_id: UUID) -> frozenset[str]: ...

    async def list_stalled_attempts(
        self,
        *,
        updated_before: datetime,
        limit: int,
    ) -> tuple[AttemptWorkItem, ...]: ...

    async def fail_expired_jobs(
        self, *, now: datetime, limit: int
    ) -> tuple[UUID, ...]: ...

    async def apply_webhook_progress(
        self,
        attempt_id: UUID,
        event: ProviderWebhookEvent,
    ) -> None: ...

    async def set_slide_result(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        object_key: str,
        mime_type: str,
        warning: str | None = None,
    ) -> None: ...

    async def fail_job(self, job_id: UUID, error: GenerationErrorInfo) -> None: ...

    async def complete_job(
        self,
        job_id: UUID,
        *,
        archive_object_key: str,
        thumbnail_object_key: str,
        thumbnail_mime_type: str,
        thumbnail_size_bytes: int,
        marketplace_text: MarketplaceTextContent | None,
        provider_used: str,
        warning: str | None,
    ) -> None: ...

    async def add_outbox(
        self,
        *,
        event_type: OutboxEventType,
        aggregate_id: UUID,
        deduplication_key: str,
        payload: Mapping[str, object],
    ) -> None: ...

    async def claim_outbox(self, *, limit: int) -> tuple[OutboxMessage, ...]: ...

    async def mark_outbox_published(self, message_id: UUID) -> None: ...

    async def mark_outbox_failed(self, message_id: UUID, error: str) -> None: ...

    async def get_webhook_payload(
        self, webhook_event_id: UUID
    ) -> dict[str, object] | None: ...

    async def mark_webhook_processed(self, webhook_event_id: UUID) -> None: ...

    async def refund_coin_once(self, job_id: UUID) -> None: ...


class ObjectStoragePort(Protocol):
    """Bounded object-storage operations used by the workflow."""

    async def upload(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None: ...

    async def download(self, object_key: str, *, max_bytes: int) -> bytes: ...

    async def presign(self, object_key: str) -> str: ...
