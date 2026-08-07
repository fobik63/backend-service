"""Unit tests for AI Circuit Breaker (CLOSED → OPEN → HALF_OPEN → CLOSED)."""

from __future__ import annotations

import fakeredis
import pytest

from app.domain.circuit_breaker import (
    CIRCUIT_TRIP_HTTP_CODES,
    CircuitBreakerConfig,
    CircuitState,
    is_trip_worthy_status,
    resolve_base_url_for_circuit,
    resolve_model_for_circuit,
    should_open_circuit,
)
from app.infrastructure import redis as redis_module
from app.infrastructure.circuit_breaker import (
    RedisCircuitBreaker,
    reset_circuit_breaker_cache,
)
from app.infrastructure.redis import (
    is_provider_circuit_open,
    record_provider_failure,
    record_provider_success,
)


@pytest.fixture(autouse=True)
def _reset_breaker_cache() -> None:
    reset_circuit_breaker_cache()
    yield
    reset_circuit_breaker_cache()


def test_trip_worthy_status_codes() -> None:
    for code in (429, 500, 502, 503):
        assert is_trip_worthy_status(code)
        assert code in CIRCUIT_TRIP_HTTP_CODES
    assert not is_trip_worthy_status(400)
    assert not is_trip_worthy_status(404)


def test_should_open_after_threshold() -> None:
    assert not should_open_circuit(2, threshold=3)
    assert should_open_circuit(3, threshold=3)


def test_resolve_fallback_model_and_base_url() -> None:
    assert (
        resolve_model_for_circuit(
            primary_model="claude-opus-4-7",
            fallback_model="claude-3-5-haiku-20241022",
            use_fallback=True,
        )
        == "claude-3-5-haiku-20241022"
    )
    assert (
        resolve_base_url_for_circuit(
            primary_base_url="https://api.anthropic.com",
            fallback_base_url="https://proxy.example/v1",
            use_fallback=True,
        )
        == "https://proxy.example/v1"
    )
    assert (
        resolve_base_url_for_circuit(
            primary_base_url="https://api.anthropic.com",
            fallback_base_url="",
            use_fallback=True,
        )
        == "https://api.anthropic.com"
    )


@pytest.mark.asyncio
async def test_redis_circuit_opens_after_three_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=3,
            failure_window_seconds=60,
            open_duration_seconds=180,
        )
    )

    assert await breaker.state("anthropic") is CircuitState.CLOSED
    await breaker.record_failure("anthropic")
    await breaker.record_failure("anthropic")
    assert await breaker.state("anthropic") is CircuitState.CLOSED
    await breaker.record_failure("anthropic")
    assert await breaker.state("anthropic") is CircuitState.OPEN

    decision = await breaker.before_call("anthropic")
    assert decision.use_fallback is True
    assert decision.state is CircuitState.OPEN
    await fake.aclose()


@pytest.mark.asyncio
async def test_success_resets_failure_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(failure_threshold=3, failure_window_seconds=60)
    )

    await breaker.record_failure("mj-nl")
    await breaker.record_failure("mj-nl")
    await breaker.record_success("mj-nl")
    await breaker.record_failure("mj-nl")
    await breaker.record_failure("mj-nl")
    assert await breaker.state("mj-nl") is CircuitState.CLOSED
    await fake.aclose()


@pytest.mark.asyncio
async def test_half_open_probe_closes_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=3,
            failure_window_seconds=60,
            open_duration_seconds=180,
            probe_lock_seconds=30,
        )
    )

    for _ in range(3):
        await breaker.record_failure("anthropic")
    assert await breaker.state("anthropic") is CircuitState.OPEN

    # Expire cool-down → HALF_OPEN
    await fake.delete("ai:circuit:anthropic:cooldown")
    state = await breaker.state("anthropic")
    assert state is CircuitState.HALF_OPEN

    probe = await breaker.before_call("anthropic")
    assert probe.is_probe is True
    assert probe.use_fallback is False

    # Concurrent callers must use fallback while probe is in flight.
    other = await breaker.before_call("anthropic")
    assert other.use_fallback is True

    await breaker.record_success("anthropic")
    assert await breaker.state("anthropic") is CircuitState.CLOSED
    await fake.aclose()


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(failure_threshold=3, open_duration_seconds=180)
    )

    for _ in range(3):
        await breaker.record_failure("anthropic")
    await fake.delete("ai:circuit:anthropic:cooldown")
    decision = await breaker.before_call("anthropic")
    assert decision.is_probe is True

    await breaker.record_failure("anthropic", trip_worthy=True)
    assert await breaker.state("anthropic") is CircuitState.OPEN
    assert await breaker.is_open("anthropic")
    await fake.aclose()


@pytest.mark.asyncio
async def test_provider_helpers_delegate_to_shared_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    reset_circuit_breaker_cache()

    assert not await is_provider_circuit_open("primary")
    await record_provider_failure("primary")
    await record_provider_failure("primary")
    await record_provider_failure("primary")

    assert await is_provider_circuit_open("primary")
    await record_provider_success("primary")
    assert not await is_provider_circuit_open("primary")
    await fake.aclose()


@pytest.mark.asyncio
async def test_non_trip_worthy_failure_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(CircuitBreakerConfig(failure_threshold=1))

    await breaker.record_failure("anthropic", trip_worthy=False)
    assert await breaker.state("anthropic") is CircuitState.CLOSED
    await fake.aclose()
