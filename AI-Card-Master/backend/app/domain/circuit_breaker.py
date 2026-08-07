"""Circuit Breaker policy for external AI API integrations.

Tracks consecutive trip-worthy failures (HTTP 429/500/502/503 or timeouts)
inside a sliding window, opens the circuit for a cool-down, then probes once
in HALF_OPEN before returning to CLOSED.

Pure domain — no Redis / HTTP / framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    """Lifecycle states of an AI provider circuit."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Trip-worthy upstream statuses (timeouts are handled separately as trip-worthy).
CIRCUIT_TRIP_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503})

# Well-known circuit names for AI integrations.
CIRCUIT_ANTHROPIC = "anthropic"
CIRCUIT_CLAUDE_VISION = "claude_vision"
CIRCUIT_STABLE_DIFFUSION = "stable_diffusion"


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """Thresholds for opening / cooling / probing a circuit."""

    failure_threshold: int = 3
    failure_window_seconds: int = 60
    open_duration_seconds: int = 180
    half_open_max_probes: int = 1
    probe_lock_seconds: int = 30

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1.")
        if self.failure_window_seconds < 1:
            raise ValueError("failure_window_seconds must be >= 1.")
        if self.open_duration_seconds < 1:
            raise ValueError("open_duration_seconds must be >= 1.")
        if self.half_open_max_probes < 1:
            raise ValueError("half_open_max_probes must be >= 1.")
        if self.probe_lock_seconds < 1:
            raise ValueError("probe_lock_seconds must be >= 1.")


@dataclass(frozen=True, slots=True)
class CircuitCallDecision:
    """Routing decision before an outbound AI call."""

    state: CircuitState
    use_fallback: bool
    is_probe: bool


def is_trip_worthy_status(status_code: int) -> bool:
    """Return True when an HTTP status should increment the failure counter."""

    return int(status_code) in CIRCUIT_TRIP_HTTP_CODES


def should_open_circuit(
    consecutive_failures: int,
    *,
    threshold: int,
) -> bool:
    """Whether consecutive trip-worthy failures should open the circuit."""

    return consecutive_failures >= max(1, threshold)


def resolve_model_for_circuit(
    *,
    primary_model: str,
    fallback_model: str,
    use_fallback: bool,
) -> str:
    """Pick primary or fallback model id without raising to the caller."""

    primary = primary_model.strip()
    fallback = fallback_model.strip()
    if use_fallback:
        return fallback or primary
    return primary or fallback


def resolve_base_url_for_circuit(
    *,
    primary_base_url: str,
    fallback_base_url: str,
    use_fallback: bool,
) -> str:
    """Pick primary or alternate proxy base URL when the circuit is open."""

    primary = primary_base_url.strip().rstrip("/")
    alternate = fallback_base_url.strip().rstrip("/")
    if use_fallback and alternate:
        return alternate
    return primary
