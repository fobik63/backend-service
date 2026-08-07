"""Anthropic Claude 4.7 integration adapters (lazy export)."""

from __future__ import annotations

from typing import Any

from app.infrastructure.claude.facades import (
    ClaudeAbTestFacade,
    ClaudeCompetitorAuditFacade,
    ClaudeExportFixFacade,
    ClaudeEyeOfGodFacade,
    ClaudeOracleFacade,
    ClaudePainAnalysisFacade,
    ClaudeRisingStarFacade,
    ClaudeStrategyFacade,
    ClaudeVisionReasoningFacade,
    ClaudeZeroHallucinationFacade,
    wrap_claude_for_domain,
)

__all__ = [
    "Claude47VisionClient",
    "ClaudeAbTestFacade",
    "ClaudeCompetitorAuditFacade",
    "ClaudeExportFixFacade",
    "ClaudeEyeOfGodFacade",
    "ClaudeOracleFacade",
    "ClaudePainAnalysisFacade",
    "ClaudeRisingStarFacade",
    "ClaudeStrategyFacade",
    "ClaudeVisionReasoningFacade",
    "ClaudeZeroHallucinationFacade",
    "wrap_claude_for_domain",
]


def __getattr__(name: str) -> Any:
    if name == "Claude47VisionClient":
        from app.infrastructure.claude.client import Claude47VisionClient

        return Claude47VisionClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
