"""Ports for AI Token & Resource Governor (plan §69 / Economy 2.0)."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.pain_analysis import PainAnalysisRequest, PainAnalysisResult
from app.domain.semantic_filter import CompetitorCardSnapshot
from app.domain.token_governor import GovernorDecision, GovernorRequest


class TokenGovernorPort(Protocol):
    """Authorize / route a Claude or local-LLM workload."""

    def authorize(self, request: GovernorRequest) -> GovernorDecision:
        """Return routing decision (cache / local / compress / Claude / reject)."""


class CompetitorSnapshotStorePort(Protocol):
    """Redis (or similar) store for prior competitor card fingerprints."""

    async def get_snapshot(
        self, *, marketplace: str, article: str
    ) -> CompetitorCardSnapshot | None:
        """Load prior snapshot for Semantic Filtering Delta."""

    async def put_snapshot(
        self,
        snapshot: CompetitorCardSnapshot,
        *,
        ttl_seconds: int,
    ) -> None:
        """Persist snapshot for the next audit of the same article."""


class LocalLlmPort(Protocol):
    """Local LLM adapter (Ollama / Llama 3) for routine text workloads."""

    @property
    def model_name(self) -> str:
        """Configured local model identifier."""

    @property
    def available(self) -> bool:
        """True when the adapter is configured and reachable enough to try."""

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        """Return (parsed_json, input_tokens_est, output_tokens_est)."""

    async def analyze_competitor_pains(
        self,
        *,
        request: PainAnalysisRequest,
        user_id: Any | None = None,
        job_id: Any | None = None,
    ) -> tuple[PainAnalysisResult, int, int]:
        """Routine pain analysis on local LLM (Haiku replacement)."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
