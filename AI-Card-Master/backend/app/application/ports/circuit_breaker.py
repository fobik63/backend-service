"""Application port for AI provider Circuit Breaker state."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.circuit_breaker import CircuitCallDecision, CircuitState


@runtime_checkable
class CircuitBreakerPort(Protocol):
    """Track OPEN / HALF_OPEN / CLOSED for named AI integrations."""

    async def state(self, name: str) -> CircuitState:
        """Return the effective circuit state (may promote OPEN → HALF_OPEN)."""

    async def before_call(self, name: str) -> CircuitCallDecision:
        """Decide whether to use the primary endpoint or a silent fallback."""

    async def record_success(self, name: str) -> None:
        """Reset failure counters and close the circuit after a healthy call."""

    async def record_failure(
        self,
        name: str,
        *,
        trip_worthy: bool = True,
    ) -> None:
        """Record a failure; trip-worthy errors may open the circuit."""

    async def is_open(self, name: str) -> bool:
        """True when the circuit is OPEN (primary traffic must be avoided)."""
