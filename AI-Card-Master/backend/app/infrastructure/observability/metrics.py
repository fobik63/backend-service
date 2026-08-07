"""Prometheus counters for fail-open side paths (audit Q4)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter
except ImportError:  # pragma: no cover - optional until dependency lands
    Counter = None  # type: ignore[misc, assignment]


if Counter is not None:
    COST_PERSIST_FAILURES = Counter(
        "cost_persist_failures",
        "API usage cost events that failed to persist (fail-open path).",
        labelnames=("provider", "operation"),
    )
else:  # pragma: no cover
    COST_PERSIST_FAILURES = None


def inc_cost_persist_failure(*, provider: str, operation: str) -> None:
    """Increment ``cost_persist_failures`` without raising into the user path."""

    if COST_PERSIST_FAILURES is None:
        return
    try:
        COST_PERSIST_FAILURES.labels(
            provider=(provider or "unknown")[:64],
            operation=(operation or "unknown")[:128],
        ).inc()
    except Exception:
        logger.debug("Failed to increment cost_persist_failures", exc_info=True)
