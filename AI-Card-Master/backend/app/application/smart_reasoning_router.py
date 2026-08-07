"""Application helpers for Smart Reasoning Routing (plan §55)."""

from __future__ import annotations

from app.domain.smart_reasoning import (
    ReasoningTaskKind,
    ReasoningTier,
    model_for_task,
    tier_for_task,
)


class SmartReasoningRouter:
    """Pure routing policy: simple → Haiku, Eye-of-God / deep → Opus."""

    def __init__(self, *, simple_model: str, deep_model: str) -> None:
        simple = simple_model.strip()
        deep = deep_model.strip()
        if not simple:
            raise ValueError("simple_model must not be empty.")
        if not deep:
            raise ValueError("deep_model must not be empty.")
        self._simple_model = simple
        self._deep_model = deep

    @property
    def simple_model(self) -> str:
        return self._simple_model

    @property
    def deep_model(self) -> str:
        return self._deep_model

    def tier_for(self, kind: ReasoningTaskKind) -> ReasoningTier:
        return tier_for_task(kind)

    def model_for(self, kind: ReasoningTaskKind) -> str:
        return model_for_task(
            kind,
            simple_model=self._simple_model,
            deep_model=self._deep_model,
        )
