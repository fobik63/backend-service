"""Ollama (local GPU) adapter for competitor negative-review pains analysis."""

from __future__ import annotations

from pydantic import ValidationError

from app.core.prompt_safety import fence_untrusted_text, harden_system_prompt
from app.domain.competitor_pains_llm import (
    COMPETITOR_PAINS_JSON_SCHEMA_HINT,
    CompetitorPainsAnalysisRequest,
    CompetitorPainsAnalysisResult,
    CompetitorPainsConfigurationError,
    CompetitorPainsLlmProvider,
    CompetitorPainsUpstreamError,
    build_competitor_pains_user_prompt,
    competitor_pains_system_prompt,
    normalize_competitor_pains_payload,
)
from app.infrastructure.ollama.client import OllamaClient, OllamaError


class OllamaCompetitorPainsClient:
    """Route competitor-pains analysis to a local Ollama node (GPU-backed)."""

    def __init__(self, ollama: OllamaClient) -> None:
        self._ollama = ollama

    @property
    def provider_name(self) -> str:
        return CompetitorPainsLlmProvider.OLLAMA.value

    @property
    def model_name(self) -> str:
        return self._ollama.model_name

    def ensure_configured(self) -> None:
        if not self._ollama.available:
            raise CompetitorPainsConfigurationError(
                "Ollama local LLM is disabled. Set OLLAMA_ENABLED=true "
                "and configure OLLAMA_BASE_URL / OLLAMA_MODEL "
                "(GPU node, e.g. http://127.0.0.1:11434)."
            )

    async def aclose(self) -> None:
        await self._ollama.aclose()

    async def analyze_negative_reviews(
        self,
        request: CompetitorPainsAnalysisRequest,
    ) -> CompetitorPainsAnalysisResult:
        self.ensure_configured()
        system = harden_system_prompt(competitor_pains_system_prompt())
        user_raw = build_competitor_pains_user_prompt(request)
        user = fence_untrusted_text(
            user_raw,
            label="competitor_negative_reviews",
            max_length=40_000,
        )
        try:
            payload, in_tok, out_tok = await self._ollama.complete_json(
                system=system,
                user=user,
                schema_hint=COMPETITOR_PAINS_JSON_SCHEMA_HINT,
            )
        except OllamaError as exc:
            raise CompetitorPainsUpstreamError(str(exc)) from exc

        try:
            return normalize_competitor_pains_payload(
                payload,
                provider=CompetitorPainsLlmProvider.OLLAMA,
                model_name=f"ollama:{self._ollama.model_name}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        except ValidationError as exc:
            raise CompetitorPainsUpstreamError(
                "Ollama response failed competitor-pains schema."
            ) from exc
