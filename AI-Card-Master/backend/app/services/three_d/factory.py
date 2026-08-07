"""Factory that resolves the configured 3D engine adapter."""

from __future__ import annotations

from functools import lru_cache
from typing import Final

from app.core.config import Settings, get_settings
from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.mock_adapter import MockThreeDEngineAdapter

SUPPORTED_THREE_D_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "mock",
        # Reserved for future adapters — register in ``create`` when ready:
        "meshy",
        "tripo",
        "runpod",
    }
)


class ThreeDEngineFactory:
    """Build a ``BaseThreeDEngine`` implementation from ``THREE_D_PROVIDER``.

    Adding Meshy / Tripo3D / RunPod later means a new adapter class plus one
    branch here — application services keep depending only on the ABC.
    """

    @staticmethod
    def create(settings: Settings | None = None) -> BaseThreeDEngine:
        cfg = settings or get_settings()
        provider = cfg.three_d_provider.strip().lower()

        if provider == "mock":
            return MockThreeDEngineAdapter(
                duration_seconds=cfg.three_d_mock_duration_seconds,
                queue_delay_seconds=cfg.three_d_mock_queue_delay_seconds,
                ticks_per_stage=cfg.three_d_mock_ticks_per_stage,
            )

        if provider in {"meshy", "tripo", "runpod"}:
            raise NotImplementedError(
                f"THREE_D_PROVIDER={provider!r} is reserved but not wired yet. "
                "Add an adapter under app.services.three_d and register it here."
            )

        raise ValueError(
            f"Unsupported THREE_D_PROVIDER={provider!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_THREE_D_PROVIDERS))}."
        )


@lru_cache(maxsize=1)
def get_three_d_engine() -> BaseThreeDEngine:
    """Process-scoped engine resolved from cached settings.

    Prefer ``ThreeDEngineFactory.create(settings)`` in tests so each case
    gets a fresh mock state and injectable config.
    """

    return ThreeDEngineFactory.create()
