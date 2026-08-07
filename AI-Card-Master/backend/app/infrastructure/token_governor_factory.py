"""Composition root for Token & Resource Governor + Ollama (plan §69)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.application.token_governor_service import TokenResourceGovernor
from app.core.config import Settings, get_settings
from app.domain.token_governor import TokenGovernorPolicy
from app.infrastructure.competitor_snapshot_store import RedisCompetitorSnapshotStore
from app.infrastructure.ollama.client import OllamaClient


@lru_cache(maxsize=1)
def get_token_governor() -> TokenResourceGovernor:
    """Process-local governor built from Settings."""

    return build_token_governor(get_settings())


def build_token_governor(settings: Settings | None = None) -> TokenResourceGovernor:
    cfg = settings or get_settings()
    policy = TokenGovernorPolicy(
        enabled=cfg.token_governor_enabled,
        ollama_enabled=cfg.ollama_enabled,
        soft_input_token_limit=cfg.token_governor_soft_input_tokens,
        hard_input_token_limit=cfg.token_governor_hard_input_tokens,
        always_semantic_filter_competitor=cfg.token_governor_always_semantic_filter,
        prefer_local_for_simple_tier=cfg.token_governor_prefer_local,
    )
    return TokenResourceGovernor(policy=policy)


def build_competitor_snapshot_store() -> RedisCompetitorSnapshotStore:
    return RedisCompetitorSnapshotStore()


def load_ollama_client(
    settings: Settings | None = None,
    *,
    require: bool = False,
    existing: Any | None = None,
) -> OllamaClient | None:
    """Return an OllamaClient when enabled; None otherwise (fail-open)."""

    if existing is not None:
        return existing

    cfg = settings or get_settings()
    if not cfg.ollama_enabled:
        if require:
            raise RuntimeError("OLLAMA_ENABLED is false.")
        return None

    base = cfg.ollama_base_url.strip()
    model = cfg.ollama_model.strip()
    if not base or not model:
        if require:
            raise RuntimeError("OLLAMA_BASE_URL and OLLAMA_MODEL are required.")
        return None

    try:
        return OllamaClient(
            base_url=base,
            model_name=model,
            timeout_seconds=cfg.ollama_timeout_seconds,
            enabled=True,
        )
    except Exception:
        if require:
            raise
        return None
