"""Application helpers for Smart Reasoning Routing (plan §55 + §69 LOCAL)."""

from __future__ import annotations

from app.domain.smart_reasoning import (
    ReasoningTaskKind,
    ReasoningTier,
    model_for_task,
    tier_for_task,
)


class SmartReasoningRouter:
    """Routing policy: simple → Haiku, deep → Opus, local → Ollama."""

    def __init__(
        self,
        *,
        simple_model: str,
        deep_model: str,
        local_model: str | None = None,
    ) -> None:
        simple = simple_model.strip()
        deep = deep_model.strip()
        if not simple:
            raise ValueError("simple_model must not be empty.")
        if not deep:
            raise ValueError("deep_model must not be empty.")
        self._simple_model = simple
        self._deep_model = deep
        self._local_model = (local_model or "").strip() or None

    @property
    def simple_model(self) -> str:
        return self._simple_model

    @property
    def deep_model(self) -> str:
        return self._deep_model

    @property
    def local_model(self) -> str | None:
        return self._local_model

    def tier_for(self, kind: ReasoningTaskKind) -> ReasoningTier:
        return tier_for_task(kind)

    def model_for(self, kind: ReasoningTaskKind) -> str:
        return model_for_task(
            kind,
            simple_model=self._simple_model,
            deep_model=self._deep_model,
            local_model=self._local_model,
        )
