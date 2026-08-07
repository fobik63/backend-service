"""Thin per-domain façades over ``Claude47VisionClient`` (audit A3).

Factories inject these wrappers instead of the god-client so each use case
depends only on the methods of its domain. Shared HTTP / retry / cost logic
stays inside ``Claude47VisionClient._messages_json``.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.claude.client import Claude47VisionClient


class ClaudeVisionReasoningFacade:
    """Chain-of-thought visual trigger analysis."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def aclose(self) -> None:
        await self._client.aclose()

    async def analyze_visual_triggers(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.analyze_visual_triggers(*args, **kwargs)

    async def align_triggers_with_text(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.align_triggers_with_text(*args, **kwargs)


class ClaudeRisingStarFacade:
    """Visual audit of rising-star competitor cards."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def dissect_rising_star_visuals(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.dissect_rising_star_visuals(*args, **kwargs)


class ClaudeEyeOfGodFacade:
    """Money-confirmed trigger vision for Eye of God."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def analyze_money_confirmed_trigger(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.analyze_money_confirmed_trigger(*args, **kwargs)


class ClaudeCompetitorAuditFacade:
    """Deep competitor card analysis."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def analyze_competitor_card(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.analyze_competitor_card(*args, **kwargs)


class ClaudeZeroHallucinationFacade:
    """OCR / claim cross-check against product facts."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def extract_and_cross_check(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.extract_and_cross_check(*args, **kwargs)


class ClaudeOracleFacade:
    """Market-gap enrichment for Oracle predictions."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def enrich_market_gaps(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.enrich_market_gaps(*args, **kwargs)


class ClaudeStrategyFacade:
    """AI strategy plan enrichment."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def enrich_strategy_plan(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.enrich_strategy_plan(*args, **kwargs)


class ClaudeAbTestFacade:
    """A/B hypothesis generation."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def generate_ab_hypotheses(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.generate_ab_hypotheses(*args, **kwargs)


class ClaudePainAnalysisFacade:
    """Competitor review pain extraction."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def analyze_competitor_pains(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.analyze_competitor_pains(*args, **kwargs)


class ClaudeExportFixFacade:
    """Marketplace export fail-safe fix suggestions."""

    def __init__(self, client: Claude47VisionClient) -> None:
        self._client = client

    async def suggest_export_fixes(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.suggest_export_fixes(*args, **kwargs)


def wrap_claude_for_domain(
    client: Claude47VisionClient | None,
    *,
    domain: str,
) -> Any | None:
    """Return a domain façade or ``None`` when Claude is unavailable."""

    if client is None:
        return None
    mapping: dict[str, type] = {
        "vision_reasoning": ClaudeVisionReasoningFacade,
        "rising_star": ClaudeRisingStarFacade,
        "eye_of_god": ClaudeEyeOfGodFacade,
        "competitor_audit": ClaudeCompetitorAuditFacade,
        "zero_hallucination": ClaudeZeroHallucinationFacade,
        "oracle": ClaudeOracleFacade,
        "strategy": ClaudeStrategyFacade,
        "ab_test": ClaudeAbTestFacade,
        "pain_analysis": ClaudePainAnalysisFacade,
        "export_fix": ClaudeExportFixFacade,
    }
    facade_cls = mapping.get(domain)
    if facade_cls is None:
        return client
    return facade_cls(client)
