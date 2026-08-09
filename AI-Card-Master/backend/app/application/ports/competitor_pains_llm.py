"""Port for LLM analysis of competitor negative-review complaints."""

from __future__ import annotations

from typing import Protocol

from app.domain.competitor_pains_llm import (
    CompetitorPainsAnalysisRequest,
    CompetitorPainsAnalysisResult,
)


class CompetitorPainsLlmPort(Protocol):
    """OpenAI or local (Ollama / OpenAI-compatible GPU) JSON analyzer."""

    @property
    def provider_name(self) -> str:
        """``openai`` or ``ollama``."""

    @property
    def model_name(self) -> str:
        """Configured upstream model id."""

    def ensure_configured(self) -> None:
        """Raise configuration error when credentials / local node are missing."""

    async def analyze_negative_reviews(
        self,
        request: CompetitorPainsAnalysisRequest,
    ) -> CompetitorPainsAnalysisResult:
        """Return 3 buyer pains + matching infographic offers."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
