"""Redis-backed Circuit Breaker for Anthropic / Midjourney / Vision / SD.

States:
- CLOSED — normal traffic; failures within ``failure_window_seconds`` count
- OPEN — cool-down ``open_duration_seconds``; callers must use fallback
- HALF_OPEN — one probe on the primary; success → CLOSED, failure → OPEN

Fail-open on Redis errors so generation stays available when the cache is down.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from redis.exceptions import RedisError

from app.application.ports.circuit_breaker import CircuitBreakerPort
from app.core.config import Settings, get_settings
from app.domain.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitCallDecision,
    CircuitState,
    should_open_circuit,
)
from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

_STATE_KEY = "ai:circuit:{name}:state"
_FAILURES_KEY = "ai:circuit:{name}:failures"
_COOLDOWN_KEY = "ai:circuit:{name}:cooldown"
_PROBE_KEY = "ai:circuit:{name}:probe"


class RedisCircuitBreaker:
    """Distributed circuit breaker using the process Redis cache client."""

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    async def state(self, name: str) -> CircuitState:
        try:
            return await self._effective_state(name)
        except RedisError:
            logger.warning(
                "Circuit breaker state read failed name=%s; treating as CLOSED",
                name,
            )
            return CircuitState.CLOSED

    async def before_call(self, name: str) -> CircuitCallDecision:
        try:
            current = await self._effective_state(name)
            if current is CircuitState.CLOSED:
                return CircuitCallDecision(
                    state=CircuitState.CLOSED,
                    use_fallback=False,
                    is_probe=False,
                )
            if current is CircuitState.OPEN:
                return CircuitCallDecision(
                    state=CircuitState.OPEN,
                    use_fallback=True,
                    is_probe=False,
                )
            # HALF_OPEN — only one concurrent probe may hit the primary.
            if await self._acquire_probe(name):
                return CircuitCallDecision(
                    state=CircuitState.HALF_OPEN,
                    use_fallback=False,
                    is_probe=True,
                )
            return CircuitCallDecision(
                state=CircuitState.HALF_OPEN,
                use_fallback=True,
                is_probe=False,
            )
        except RedisError:
            logger.warning(
                "Circuit breaker before_call failed name=%s; allowing primary",
                name,
            )
            return CircuitCallDecision(
                state=CircuitState.CLOSED,
                use_fallback=False,
                is_probe=False,
            )

    async def record_success(self, name: str) -> None:
        try:
            client = get_redis_client()
            await client.delete(
                _failures_key(name),
                _cooldown_key(name),
                _probe_key(name),
                _state_key(name),
            )
            await client.set(_state_key(name), CircuitState.CLOSED.value)
        except RedisError:
            logger.warning("Could not reset circuit breaker name=%s", name)

    async def record_failure(
        self,
        name: str,
        *,
        trip_worthy: bool = True,
    ) -> None:
        if not trip_worthy:
            return
        try:
            client = get_redis_client()
            current = await self._effective_state(name)
            if current is CircuitState.HALF_OPEN:
                await self._open_circuit(name)
                return

            failures_key = _failures_key(name)
            failures = int(await client.incr(failures_key))
            if failures == 1:
                await client.expire(
                    failures_key,
                    self._config.failure_window_seconds,
                )
            if should_open_circuit(
                failures,
                threshold=self._config.failure_threshold,
            ):
                await self._open_circuit(name)
        except RedisError:
            logger.warning("Could not update circuit breaker name=%s", name)

    async def is_open(self, name: str) -> bool:
        return (await self.state(name)) is CircuitState.OPEN

    async def _effective_state(self, name: str) -> CircuitState:
        client = get_redis_client()
        raw = await client.get(_state_key(name))
        if raw is None:
            return CircuitState.CLOSED
        try:
            current = CircuitState(str(raw))
        except ValueError:
            await client.delete(_state_key(name))
            return CircuitState.CLOSED

        if current is CircuitState.OPEN:
            # Cool-down elapsed → promote to HALF_OPEN for a single probe.
            if not await client.exists(_cooldown_key(name)):
                await client.set(_state_key(name), CircuitState.HALF_OPEN.value)
                await client.delete(_probe_key(name))
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN

        if current is CircuitState.HALF_OPEN:
            return CircuitState.HALF_OPEN

        return CircuitState.CLOSED

    async def _open_circuit(self, name: str) -> None:
        client = get_redis_client()
        await client.set(_state_key(name), CircuitState.OPEN.value)
        await client.set(
            _cooldown_key(name),
            "1",
            ex=self._config.open_duration_seconds,
        )
        await client.delete(_failures_key(name), _probe_key(name))
        logger.warning(
            "Circuit breaker OPEN name=%s for %ss after consecutive failures",
            name,
            self._config.open_duration_seconds,
        )

    async def _acquire_probe(self, name: str) -> bool:
        client = get_redis_client()
        acquired = await client.set(
            _probe_key(name),
            "1",
            nx=True,
            ex=self._config.probe_lock_seconds,
        )
        return bool(acquired)


def _state_key(name: str) -> str:
    return _STATE_KEY.format(name=_normalize_name(name))


def _failures_key(name: str) -> str:
    return _FAILURES_KEY.format(name=_normalize_name(name))


def _cooldown_key(name: str) -> str:
    return _COOLDOWN_KEY.format(name=_normalize_name(name))


def _probe_key(name: str) -> str:
    return _PROBE_KEY.format(name=_normalize_name(name))


def _normalize_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Circuit breaker name must not be empty.")
    return normalized


def circuit_breaker_config_from_settings(
    settings: Settings | None = None,
) -> CircuitBreakerConfig:
    """Build domain config from application settings."""

    cfg = settings or get_settings()
    return CircuitBreakerConfig(
        failure_threshold=cfg.ai_circuit_breaker_failure_threshold,
        failure_window_seconds=cfg.ai_circuit_breaker_failure_window_seconds,
        open_duration_seconds=cfg.ai_circuit_breaker_open_duration_seconds,
        half_open_max_probes=1,
        probe_lock_seconds=cfg.ai_circuit_breaker_probe_lock_seconds,
    )


@lru_cache(maxsize=1)
def get_circuit_breaker() -> CircuitBreakerPort:
    """Process-local Redis circuit breaker (shared across AI adapters)."""

    return RedisCircuitBreaker(circuit_breaker_config_from_settings())


def reset_circuit_breaker_cache() -> None:
    """Clear the cached breaker (tests only)."""

    get_circuit_breaker.cache_clear()
