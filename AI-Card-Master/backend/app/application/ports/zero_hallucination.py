"""Ports for Zero-Hallucination OCR ↔ description cross-check (plan §57)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.zero_hallucination import ClaudeCrossCheckPayload


class ZeroHallucinationCrossCheckPort(Protocol):
    """Claude Vision adapter: OCR claims vs listing text dual verification."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def extract_and_cross_check(
        self,
        *,
        images: tuple[tuple[bytes, str], ...],
        title: str | None,
        description: str | None,
        specs: list[str],
        marketplace: str | None = None,
        article: str | None = None,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[ClaudeCrossCheckPayload, int, int]:
        """Vision OCR + text alignment → raw Claude payload + token usage."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
