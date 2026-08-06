"""Ports for intelligent Claude 4.7 visual audit (Rising Stars)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.visual_audit import (
    RisingStarVisionDissection,
    VisualAuditJobStatus,
    VisualAuditJobView,
)


class VisualAuditPersistencePort(Protocol):
    """Durable storage for niche visual-audit jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        cards_payload: list[dict[str, Any]],
        filter_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> VisualAuditJobView:
        """Persist a queued visual-audit job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VisualAuditJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> VisualAuditJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> VisualAuditJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: VisualAuditJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> VisualAuditJobView:
        """Update job lifecycle status."""

    async def save_filter_report(
        self,
        *,
        job_id: UUID,
        filter_report: dict[str, Any],
    ) -> VisualAuditJobView:
        """Persist deterministic pre-Vision filter report."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        vision_dissections: list[dict[str, Any]],
        generator_config: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> VisualAuditJobView:
        """Persist Rising Star dissections + generator JSON and mark completed."""


class RisingStarVisionPort(Protocol):
    """Claude Vision adapter for Rising Star visual dissection."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def dissect_rising_star_visuals(
        self,
        *,
        sku: str,
        title: str | None,
        product_category: str | None,
        sales_growth_ratio: float | None,
        review_velocity_per_day: float,
        review_count: int,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[RisingStarVisionDissection, int, int]:
        """Deep visual audit for one Rising Star card.

        Returns (dissection, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""
