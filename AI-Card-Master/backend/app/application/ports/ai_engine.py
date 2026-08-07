"""Ports isolating application use cases from concrete AI engine services (A1)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FaceFixPort(Protocol):
    """Optional face restoration after HD generation."""

    async def fix_if_needed(self, image_bytes: bytes) -> bytes:
        """Return corrected bytes, or the original image when no fix is needed."""


@runtime_checkable
class ProviderHealthPort(Protocol):
    """Record provider success / failure for pool health routing."""

    async def note_success(self, provider_name: str) -> None:
        """Mark a provider attempt as healthy."""

    async def note_failure(self, provider_name: str) -> None:
        """Mark a provider attempt as failed."""

    async def allow_primary(self, provider_name: str) -> bool:
        """False when the circuit is OPEN or a non-probe HALF_OPEN slot."""


@runtime_checkable
class AIEnginePort(Protocol):
    """Façade bundling face-fix and provider health used by generation."""

    @property
    def face_fix(self) -> FaceFixPort:
        """Face restoration adapter."""

    @property
    def provider_health(self) -> ProviderHealthPort:
        """Provider pool health tracker."""
