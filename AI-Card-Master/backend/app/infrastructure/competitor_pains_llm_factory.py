"""Composition root for competitor negative-review LLM pain analysis."""

from __future__ import annotations

import os

from app.application.competitor_pains_llm_service import CompetitorPainsLlmService
from app.core.config import Settings, get_settings
from app.domain.competitor_pains_llm import (
    CompetitorPainsConfigurationError,
    CompetitorPainsLlmProvider,
)
from app.infrastructure.ollama.competitor_pains_client import OllamaCompetitorPainsClient
from app.infrastructure.openai.competitor_pains_client import OpenAiCompetitorPainsClient
from app.infrastructure.token_governor_factory import load_ollama_client


def resolve_competitor_pains_provider(
    settings: Settings | None = None,
) -> CompetitorPainsLlmProvider:
    """Pick OpenAI cloud or local Ollama GPU node.

    Env (first match wins):
    - ``COMPETITOR_PAINS_LLM_PROVIDER`` = ``openai`` | ``ollama``
    - else if ``OLLAMA_ENABLED=true`` and no OpenAI key → ``ollama``
    - else ``openai`` (supports ``LLM_BASE_URL`` pointing at a local
      OpenAI-compatible GPU server such as vLLM / LM Studio).
    """

    cfg = settings or get_settings()
    raw = (
        os.getenv("COMPETITOR_PAINS_LLM_PROVIDER", "").strip().casefold()
        or "auto"
    )
    if raw in {"ollama", "local", "local_ollama"}:
        return CompetitorPainsLlmProvider.OLLAMA
    if raw in {"openai", "gpt"}:
        return CompetitorPainsLlmProvider.OPENAI

    has_openai_key = bool(
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("LLM_API_KEY", "").strip()
    )
    if cfg.ollama_enabled and not has_openai_key:
        return CompetitorPainsLlmProvider.OLLAMA
    return CompetitorPainsLlmProvider.OPENAI


def build_competitor_pains_llm_service(
    settings: Settings | None = None,
) -> CompetitorPainsLlmService:
    """Wire OpenAI or Ollama adapter for analytics handlers."""

    cfg = settings or get_settings()
    provider = resolve_competitor_pains_provider(cfg)

    if provider is CompetitorPainsLlmProvider.OLLAMA:
        ollama = load_ollama_client(cfg)
        if ollama is None:
            raise CompetitorPainsConfigurationError(
                "COMPETITOR_PAINS_LLM_PROVIDER=ollama but Ollama is not configured. "
                "Set OLLAMA_ENABLED=true, OLLAMA_BASE_URL, OLLAMA_MODEL."
            )
        return CompetitorPainsLlmService(OllamaCompetitorPainsClient(ollama))

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com").strip()
    # Local OpenAI-compatible GPU nodes often accept a dummy key.
    is_local_compatible = "api.openai.com" not in base_url.casefold()
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45") or 45)
    max_retries = int(os.getenv("LLM_MAX_RETRIES", "2") or 2)
    client = OpenAiCompetitorPainsClient(
        model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        base_url=base_url,
        timeout_seconds=timeout,
        max_retries=max_retries,
        require_api_key=not is_local_compatible,
    )
    return CompetitorPainsLlmService(client)
