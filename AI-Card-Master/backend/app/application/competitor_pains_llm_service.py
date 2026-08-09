"""Application service: competitor complaint corpus → LLM pains + offers."""

from __future__ import annotations

import logging

from app.application.ports.competitor_pains_llm import CompetitorPainsLlmPort
from app.domain.competitor_pains_llm import (
    CompetitorPainsAnalysisRequest,
    CompetitorPainsAnalysisResult,
    CompetitorPainsConfigurationError,
    CompetitorPainsUpstreamError,
    CompetitorPainsValidationError,
)

logger = logging.getLogger(__name__)


class CompetitorPainsLlmService:
    """Send collected negative competitor reviews to OpenAI or local GPU LLM."""

    def __init__(self, llm: CompetitorPainsLlmPort) -> None:
        self._llm = llm

    async def analyze_negative_reviews(
        self,
        request: CompetitorPainsAnalysisRequest,
    ) -> CompetitorPainsAnalysisResult:
        """Analyze ``complaint_texts`` and return structured pains + recommendations."""

        if not request.complaint_texts:
            raise CompetitorPainsValidationError(
                "At least one negative review complaint is required."
            )

        ensure = getattr(self._llm, "ensure_configured", None)
        if callable(ensure):
            ensure()

        try:
            result = await self._llm.analyze_negative_reviews(request)
        except CompetitorPainsConfigurationError:
            raise
        except CompetitorPainsUpstreamError:
            raise
        except Exception as exc:
            logger.exception(
                "Competitor pains LLM failed provider=%s model=%s",
                getattr(self._llm, "provider_name", "?"),
                getattr(self._llm, "model_name", "?"),
            )
            raise CompetitorPainsUpstreamError(
                f"LLM analysis failed: {exc}"
            ) from exc

        return result

    async def aclose(self) -> None:
        await self._llm.aclose()
