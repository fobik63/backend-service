"""Ports for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.ai_strategy import (
    ClaudeStrategyEnrichment,
    StrategyCompareReport,
    StrategyJobStatus,
    StrategyJobView,
)


class StrategyPersistencePort(Protocol):
    """Durable storage for AI Strategy jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        user_card_payload: dict[str, Any],
        leader_card_payload: dict[str, Any],
        compare_config: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> StrategyJobView:
        """Persist a queued AI Strategy job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> StrategyJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> StrategyJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> StrategyJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: StrategyJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> StrategyJobView:
        """Update job lifecycle status."""

    async def save_compare_report(
        self,
        *,
        job_id: UUID,
        compare_report: dict[str, Any],
    ) -> StrategyJobView:
        """Persist deterministic user-vs-leader comparison."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        plan_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> StrategyJobView:
        """Persist killer plan and mark completed."""


class StrategyPlanningPort(Protocol):
    """Claude JSON adapter for killer-plan enrichment."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def enrich_strategy_plan(
        self,
        *,
        compare_report: StrategyCompareReport,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[list[ClaudeStrategyEnrichment], str, int, int]:
        """Refine step titles/instructions while keeping CTR rationales.

        Returns (enrichments, executive_summary, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""
