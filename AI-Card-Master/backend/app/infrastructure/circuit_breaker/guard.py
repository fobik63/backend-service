"""Helpers that wrap outbound AI calls with Circuit Breaker + silent fallback."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.application.ports.circuit_breaker import CircuitBreakerPort
from app.domain.circuit_breaker import CircuitCallDecision, is_trip_worthy_status

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerOpenError(RuntimeError):
    """Raised only when no fallback path exists and the circuit is OPEN."""


async def execute_with_circuit_breaker(
    *,
    breaker: CircuitBreakerPort,
    circuit_name: str,
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]] | None = None,
    is_trip_worthy_exc: Callable[[BaseException], bool] | None = None,
) -> T:
    """Run ``primary`` or silent ``fallback`` according to circuit state.

    - CLOSED: primary
    - OPEN: fallback (if provided); otherwise raises ``CircuitBreakerOpenError``
    - HALF_OPEN probe: primary; success closes, trip-worthy failure re-opens
    - HALF_OPEN non-probe: fallback when available
    """

    decision = await breaker.before_call(circuit_name)
    use_fallback = decision.use_fallback and fallback is not None
    operation = fallback if use_fallback else primary

    if decision.use_fallback and fallback is None:
        raise CircuitBreakerOpenError(
            f"Circuit '{circuit_name}' is {decision.state.value} and no fallback "
            "is configured."
        )

    if use_fallback:
        logger.info(
            "Circuit breaker routing to fallback name=%s state=%s probe=%s",
            circuit_name,
            decision.state.value,
            decision.is_probe,
        )

    try:
        result = await operation()
    except BaseException as exc:
        trip = True
        if is_trip_worthy_exc is not None:
            trip = is_trip_worthy_exc(exc)
        # Fallback traffic must not re-trip the primary circuit.
        if not use_fallback:
            await breaker.record_failure(circuit_name, trip_worthy=trip)
        raise

    if not use_fallback:
        await breaker.record_success(circuit_name)
    return result


def trip_worthy_from_http_status(status_code: int | None) -> bool:
    """Map an optional HTTP status to a trip-worthy failure flag."""

    if status_code is None:
        return True  # timeout / transport without status
    return is_trip_worthy_status(status_code)


def log_circuit_decision(circuit_name: str, decision: CircuitCallDecision) -> None:
    """Emit a structured debug line for adapter wiring."""

    logger.debug(
        "Circuit decision name=%s state=%s fallback=%s probe=%s",
        circuit_name,
        decision.state.value,
        decision.use_fallback,
        decision.is_probe,
    )
