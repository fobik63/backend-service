"""Ports for Smart Reasoning Routing & analytics caching (plan §55)."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.smart_reasoning import ReasoningTaskKind, ReasoningTier


class ReasoningModelRouterPort(Protocol):
    """Resolve Claude model id for a named analytics workload."""

    def model_for(self, kind: ReasoningTaskKind) -> str:
        """Return Haiku (simple) or Opus (deep / Eye of God)."""

    def tier_for(self, kind: ReasoningTaskKind) -> ReasoningTier:
        """Return the cost tier for the workload."""


class AnalyticsCachePort(Protocol):
    """Fail-open Redis cache for completed Claude analytics JSON (24h TTL)."""

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return a cached JSON object or None."""

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        """Store a JSON object with TTL; may no-op when Redis is down."""
