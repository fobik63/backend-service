"""Ports for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.oracle import (
    ClaudeGapEnrichment,
    OracleJobStatus,
    OracleJobView,
    OracleScanReport,
)


class OraclePersistencePort(Protocol):
    """Durable storage for Oracle prediction jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        queries_payload: list[dict[str, Any]],
        supply_payload: list[dict[str, Any]],
        gap_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> OracleJobView:
        """Persist a queued Oracle job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> OracleJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> OracleJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> OracleJobView | None:
        """Load a job by id (worker path)."""

    async def list_recent_notifications(
        self, *, user_id: UUID, limit: int = 20
    ) -> list[OracleJobView]:
        """Recent completed jobs that emitted niche notifications."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: OracleJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> OracleJobView:
        """Update job lifecycle status."""

    async def save_scan_report(
        self,
        *,
        job_id: UUID,
        scan_report: dict[str, Any],
    ) -> OracleJobView:
        """Persist deterministic demand/supply scan."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        prediction_result: dict[str, Any],
        notifications: list[str],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> OracleJobView:
        """Persist prediction + niche alerts and mark completed."""


class OracleEnrichmentPort(Protocol):
    """Claude JSON adapter for niche-gap enrichment."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def enrich_market_gaps(
        self,
        *,
        scan_report: OracleScanReport,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[list[ClaudeGapEnrichment], int, int]:
        """Refine style labels and notification copy for detected gaps.

        Returns (enrichments, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""
