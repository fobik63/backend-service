"""Ports for manual competitor-link audit + Claude deep analysis (plan §77–78)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.competitor_audit import (
    CompetitorAuditJobStatus,
    CompetitorAuditJobView,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    CompetitorProductLink,
)


class CompetitorAuditPersistencePort(Protocol):
    """Durable storage for competitor-audit scrape + analysis jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        links: list[str],
        idempotency_key: str | None = None,
    ) -> CompetitorAuditJobView:
        """Persist a queued competitor-audit job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> CompetitorAuditJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> CompetitorAuditJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> CompetitorAuditJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: CompetitorAuditJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> CompetitorAuditJobView:
        """Update job lifecycle status."""

    async def save_scrape_result(
        self,
        *,
        job_id: UUID,
        result_payload: dict[str, Any],
    ) -> CompetitorAuditJobView:
        """Persist scrape result and move job to ANALYZING (Claude next)."""

    async def save_analysis_result(
        self,
        *,
        job_id: UUID,
        analysis_payload: dict[str, Any],
        model_name: str,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> CompetitorAuditJobView:
        """Persist Claude deep-analysis JSON and mark COMPLETED."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        result_payload: dict[str, Any],
    ) -> CompetitorAuditJobView:
        """Legacy alias: persist scrape-only completion (tests / fallback)."""


class CompetitorDeepScraperPort(Protocol):
    """Deep WB/Ozon mobile-JSON scraper (gallery, specs, prices, reviews)."""

    async def scrape_card(
        self, link: CompetitorProductLink
    ) -> CompetitorCardScrapeResult:
        """Fetch maximum raw card data for one validated product link."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class CompetitorDeepAnalysisPort(Protocol):
    """Claude 4.7 Opus Vision + text deep audit for one scraped card."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def analyze_competitor_card(
        self,
        *,
        card: CompetitorCardScrapeResult,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
        context_delta: Any | None = None,
    ) -> tuple[CompetitorCardDeepAnalysis, int, int]:
        """Run three-vector audit; return (result, input_tokens, output_tokens)."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class CompetitorCardImagePort(Protocol):
    """Download gallery photos for Claude Vision."""

    async def fetch_urls(
        self,
        *,
        urls: list[str],
        max_images: int = 5,
    ) -> tuple[tuple[bytes, str, str], ...]:
        """Return ((bytes, mime_type, source_url), ...) for Vision."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class CompetitorDeepAnalysisTriggerPort(Protocol):
    """Enqueue Claude deep-analysis Celery task after scrape completes."""

    def enqueue_deep_analysis(self, *, job_id: UUID) -> str:
        """Publish task; return celery task id."""
