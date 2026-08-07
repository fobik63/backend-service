"""Factory that resolves the configured 3D engine adapter."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Final

from pydantic import SecretStr

from app.application.ports.circuit_breaker import CircuitBreakerPort
from app.core.config import Settings, get_settings
from app.services.three_d.adapters.meshy import MeshyEngineAdapter
from app.services.three_d.adapters.tripo3d import Tripo3DEngineAdapter
from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.failover import FailoverThreeDEngine
from app.services.three_d.mock_adapter import MockThreeDEngineAdapter

logger = logging.getLogger(__name__)

SUPPORTED_THREE_D_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "mock",
        "meshy",
        "tripo",
        "tripo3d",
        "runpod",
    }
)


class ThreeDEngineFactory:
    """Build a ``BaseThreeDEngine`` implementation from ``THREE_D_PROVIDER``.

    ``meshy`` / ``tripo3d`` (alias ``tripo``) require API keys; when a key is
    missing the factory logs a warning and falls back to the mock adapter so
    local/dev environments keep working.

    Live Meshy/Tripo adapters receive the shared Redis CircuitBreaker. When both
    API keys are present, the non-primary provider is wired as a silent failover
    once the primary circuit opens after repeated 429/5xx responses.
    """

    @staticmethod
    def create(
        settings: Settings | None = None,
        *,
        circuit_breaker: CircuitBreakerPort | None = None,
    ) -> BaseThreeDEngine:
        cfg = settings or get_settings()
        provider = cfg.three_d_provider.strip().lower()
        breaker = circuit_breaker
        if breaker is None and provider in {"meshy", "tripo", "tripo3d"}:
            from app.infrastructure.circuit_breaker import get_circuit_breaker

            breaker = get_circuit_breaker()

        if provider == "mock":
            return ThreeDEngineFactory._mock(cfg)

        if provider == "meshy":
            primary = ThreeDEngineFactory._meshy(cfg, breaker)
            if primary is None:
                return ThreeDEngineFactory._mock(cfg)
            fallback = ThreeDEngineFactory._tripo(cfg, breaker)
            if fallback is None:
                return primary
            return FailoverThreeDEngine(
                primary,
                fallback,
                primary_name="meshy",
                fallback_name="tripo3d",
            )

        if provider in {"tripo3d", "tripo"}:
            primary = ThreeDEngineFactory._tripo(cfg, breaker)
            if primary is None:
                return ThreeDEngineFactory._mock(cfg)
            fallback = ThreeDEngineFactory._meshy(cfg, breaker)
            if fallback is None:
                return primary
            return FailoverThreeDEngine(
                primary,
                fallback,
                primary_name="tripo3d",
                fallback_name="meshy",
            )

        if provider == "runpod":
            raise NotImplementedError(
                "THREE_D_PROVIDER='runpod' is reserved but not wired yet. "
                "Add an adapter under app.services.three_d and register it here."
            )

        raise ValueError(
            f"Unsupported THREE_D_PROVIDER={provider!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_THREE_D_PROVIDERS))}."
        )

    @staticmethod
    def _meshy(
        cfg: Settings,
        breaker: CircuitBreakerPort | None,
    ) -> MeshyEngineAdapter | None:
        api_key = _secret_value(getattr(cfg, "meshy_api_key", None))
        if not api_key:
            provider = str(getattr(cfg, "three_d_provider", "")).strip().lower()
            if provider == "meshy":
                logger.warning(
                    "THREE_D_PROVIDER=meshy but MESHY_API_KEY is unset; "
                    "falling back to MockThreeDEngineAdapter."
                )
            else:
                logger.info("MESHY_API_KEY unset; Meshy failover adapter unavailable.")
            return None
        return MeshyEngineAdapter(
            api_key=api_key,
            base_url=str(getattr(cfg, "meshy_base_url", "https://api.meshy.ai/v2")),
            timeout_seconds=float(getattr(cfg, "meshy_timeout_seconds", 60.0)),
            circuit_breaker=breaker,
        )

    @staticmethod
    def _tripo(
        cfg: Settings,
        breaker: CircuitBreakerPort | None,
    ) -> Tripo3DEngineAdapter | None:
        api_key = _secret_value(getattr(cfg, "tripo3d_api_key", None))
        if not api_key:
            provider = str(getattr(cfg, "three_d_provider", "")).strip().lower()
            if provider in {"tripo", "tripo3d"}:
                logger.warning(
                    "THREE_D_PROVIDER=%s but TRIPO3D_API_KEY/TRIPO_API_KEY is unset; "
                    "falling back to MockThreeDEngineAdapter.",
                    provider,
                )
            else:
                logger.info(
                    "TRIPO3D_API_KEY unset; Tripo3D failover adapter unavailable."
                )
            return None
        return Tripo3DEngineAdapter(
            api_key=api_key,
            base_url=str(
                getattr(cfg, "tripo3d_base_url", "https://api.tripo3d.ai/v2/openapi")
            ),
            timeout_seconds=float(getattr(cfg, "tripo3d_timeout_seconds", 60.0)),
            circuit_breaker=breaker,
        )

    @staticmethod
    def _mock(cfg: Settings) -> MockThreeDEngineAdapter:
        return MockThreeDEngineAdapter(
            duration_seconds=cfg.three_d_mock_duration_seconds,
            queue_delay_seconds=cfg.three_d_mock_queue_delay_seconds,
            ticks_per_stage=cfg.three_d_mock_ticks_per_stage,
        )


def _secret_value(value: SecretStr | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        raw = value.get_secret_value().strip()
    else:
        raw = str(value).strip()
    return raw or None


@lru_cache(maxsize=1)
def get_three_d_engine() -> BaseThreeDEngine:
    """Process-scoped engine resolved from cached settings.

    Prefer ``ThreeDEngineFactory.create(settings)`` in tests so each case
    gets a fresh mock state and injectable config.
    """

    return ThreeDEngineFactory.create()


async def close_three_d_engine() -> None:
    """Close the process-scoped 3D engine (httpx clients / mock runners)."""

    engine = get_three_d_engine.cache_info()
    if engine.currsize == 0:
        return
    try:
        await get_three_d_engine().aclose()
    finally:
        get_three_d_engine.cache_clear()
