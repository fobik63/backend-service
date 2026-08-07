"""Ports for Fail-Safe Export sandbox Claude auto-fix (plan §59)."""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from uuid import UUID

from app.domain.export import MarketplacePlatform, ValidationIssue
from app.domain.export_fail_safe import ExportFixSuggestion


class ExportFixSuggestPort(Protocol):
    """Claude adapter that proposes a corrected card after sandbox errors."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def suggest_export_fixes(
        self,
        *,
        platform: MarketplacePlatform,
        title: str,
        description: str,
        characteristics: tuple[str, ...],
        issues: tuple[ValidationIssue, ...],
        product_category: str | None = None,
        extras: Mapping[str, Any] | None = None,
        title_max: int,
        description_max: int,
        characteristics_max: int,
        characteristic_max_length: int,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[ExportFixSuggestion, int, int]:
        """Rewrite card text / category hints to clear validator errors."""

    async def aclose(self) -> None:
        """Release HTTP resources."""
