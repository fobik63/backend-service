"""Ports for competitor negative-review pain analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.pain_analysis import (
    PainAnalysisJobStatus,
    PainAnalysisJobView,
    PainAnalysisRequest,
    PainAnalysisResult,
)


class PainAnalysisPersistencePort(Protocol):
    """Durable storage for pain-analysis jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        product_name: str,
        platform: str,
        request_payload: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> PainAnalysisJobView:
        """Persist a queued pain-analysis job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> PainAnalysisJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> PainAnalysisJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> PainAnalysisJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: PainAnalysisJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> PainAnalysisJobView:
        """Update job lifecycle status."""

    async def save_filter_preview(
        self,
        *,
        job_id: UUID,
        filter_preview: dict[str, Any],
    ) -> PainAnalysisJobView:
        """Persist deterministic junk-filter preview."""

    async def save_filter_checkpoint(
        self,
        *,
        job_id: UUID,
        filter_preview: dict[str, Any],
        next_status: PainAnalysisJobStatus,
    ) -> PainAnalysisJobView:
        """Persist filter preview and advance status in one DB round-trip."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        analysis_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> PainAnalysisJobView:
        """Persist analysis result and mark completed."""


class PainAnalysisClaudePort(Protocol):
    """Claude JSON adapter for pain analysis."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def analyze_competitor_pains(
        self,
        *,
        request: PainAnalysisRequest,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[PainAnalysisResult, int, int]:
        """Filter junk reviews and produce pain-closing marketplace content.

        Returns (result, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""
