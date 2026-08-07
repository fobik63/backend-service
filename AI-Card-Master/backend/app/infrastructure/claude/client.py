"""Anthropic Claude 4.7 Opus client: Vision API + JSON Mode + CoT stages."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.prompt_safety import harden_system_prompt
from app.domain.ab_test import (
    AB_HYPOTHESES_JSON_SCHEMA,
    AbProductBrief,
    AbVariantHypothesis,
    ab_system_prompt,
    build_ab_hypotheses_prompt,
    normalize_hypotheses,
)
from app.domain.ai_strategy import (
    STRATEGY_PLAN_JSON_SCHEMA,
    ClaudeStrategyEnrichment,
    StrategyActionType,
    StrategyCompareReport,
    build_ctr_rationale,
    build_strategy_plan_prompt,
    strategy_system_prompt,
)
from app.domain.claude_reasoning import (
    REASONING_JSON_SCHEMA,
    VISION_JSON_SCHEMA,
    CompetitorTextContext,
    ReasoningStageResult,
    VisionStageResult,
    build_reasoning_user_prompt,
    build_vision_user_prompt,
    extract_json_object,
    reasoning_system_prompt,
    vision_system_prompt,
)
from app.domain.oracle import (
    ORACLE_ENRICHMENT_JSON_SCHEMA,
    ClaudeGapEnrichment,
    OracleScanReport,
    build_niche_notification,
    build_oracle_enrichment_prompt,
    oracle_system_prompt,
)
from app.domain.pain_analysis import (
    PAIN_ANALYSIS_JSON_SCHEMA,
    PainAnalysisRequest,
    PainAnalysisResult,
    build_pain_analysis_prompt,
    normalize_claude_pain_result,
    pain_analysis_system_prompt,
)
from app.domain.eye_of_god import (
    MONEY_CONFIRMED_VISION_JSON_SCHEMA,
    MoneyConfirmedVisionResult,
    build_eye_of_god_vision_prompt,
    eye_of_god_vision_system_prompt,
)
from app.domain.competitor_audit import (
    COMPETITOR_DEEP_ANALYSIS_JSON_SCHEMA,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    build_competitor_deep_analysis_prompt,
    competitor_deep_analysis_system_prompt,
    normalize_deep_analysis_card,
)
from app.domain.zero_hallucination import (
    ZERO_HALLUCINATION_JSON_SCHEMA,
    ClaudeCrossCheckPayload,
    build_cross_check_user_prompt,
    cross_check_system_prompt,
)
from app.domain.export import MarketplacePlatform, ValidationIssue
from app.domain.export_fail_safe import (
    EXPORT_FIX_JSON_SCHEMA,
    ExportFixSuggestion,
    build_export_fix_prompt,
    export_fix_system_prompt,
    normalize_export_fix_payload,
)
from app.domain.visual_audit import (
    RISING_STAR_VISION_JSON_SCHEMA,
    RisingStarVisionDissection,
    build_rising_star_vision_prompt,
    rising_star_vision_system_prompt,
)
from app.domain.smart_reasoning import (
    fingerprint_messages_request,
    model_for_task,
    model_supports_adaptive_thinking,
    ReasoningTaskKind,
    redis_analytics_key,
)
from app.infrastructure.claude.image_normalize import normalize_image_for_claude
from app.services.api_usage_costs import record_api_usage_cost
from app.services.infographic_service import TRANSIENT_HTTP_CODES

logger = logging.getLogger(__name__)

# Operations whose ``job_id`` is a real ``generation_jobs.id`` (FK-safe).
_GENERATION_JOB_LINKED_OPERATIONS: frozenset[str] = frozenset(
    {
        "claude_export_fail_safe_fix",
        "claude_zero_hallucination_cross_check",
    }
)


class ClaudeIntegrationError(Exception):
    """Base Claude 4.7 integration failure."""


class ClaudeConfigurationError(ClaudeIntegrationError):
    """Missing or invalid Claude API settings."""


class ClaudeUpstreamError(ClaudeIntegrationError):
    """Upstream Anthropic request/response cannot be trusted."""


class Claude47VisionClient:
    """Async Anthropic Messages client for Vision + structured JSON CoT.

    Plan §55: ``model_name`` selects Haiku (simple) vs Opus (deep / Eye of God).
    Optional ``analytics_cache`` stores identical request results for 24h.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_name: str | None = None,
        analytics_cache: Any | None = None,
        analytics_cache_ttl_seconds: int | None = None,
        analytics_task_kind: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        api_key = self._settings.claude_47_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise ClaudeConfigurationError(
                "CLAUDE_47_API_KEY is required for Claude Vision reasoning."
            )
        self._api_key = api_key.get_secret_value().strip()
        resolved = (model_name or self._settings.claude_47_model).strip()
        if not resolved:
            raise ClaudeConfigurationError(
                "Claude model name must not be empty "
                "(CLAUDE_47_MODEL / CLAUDE_35_HAIKU_MODEL)."
            )
        self._model = resolved
        self._adaptive = model_supports_adaptive_thinking(self._model)
        self._analytics_cache = analytics_cache
        ttl = (
            analytics_cache_ttl_seconds
            if analytics_cache_ttl_seconds is not None
            else self._settings.claude_analytics_cache_ttl_seconds
        )
        if ttl <= 0:
            raise ClaudeConfigurationError(
                "claude_analytics_cache_ttl_seconds must be positive."
            )
        self._analytics_cache_ttl_seconds = ttl
        self._analytics_task_kind = (analytics_task_kind or "claude").strip() or "claude"
        # Single HTTP transport: official AsyncAnthropic SDK (no parallel httpx pool).
        self._sdk = AsyncAnthropic(
            api_key=self._api_key,
            base_url=self._settings.claude_47_base_url.rstrip("/"),
            timeout=self._settings.claude_47_timeout_seconds,
            max_retries=0,
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def uses_adaptive_thinking(self) -> bool:
        return self._adaptive

    async def aclose(self) -> None:
        await self._sdk.close()

    async def analyze_visual_triggers(
        self,
        *,
        images: tuple[tuple[bytes, str], ...],
        product_category: str | None,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[VisionStageResult, int, int]:
        if not images:
            raise ClaudeUpstreamError("At least one competitor image is required.")
        image_blocks, image_count = _encode_vision_image_blocks(
            images,
            max_images=self._settings.claude_47_max_images_per_request,
        )
        content: list[dict[str, Any]] = [
            *image_blocks,
            {
                "type": "text",
                "text": build_vision_user_prompt(
                    product_category=product_category,
                    image_count=image_count,
                ),
            },
        ]
        return await self._messages_parse(
            system=vision_system_prompt(),
            content=content,
            output_format=VisionStageResult,
            max_tokens=self._settings.claude_47_vision_max_tokens,
            operation="claude_vision_triggers",
            user_id=user_id,
            job_id=job_id,
            fallback_schema=VISION_JSON_SCHEMA,
        )

    async def align_triggers_with_text(
        self,
        *,
        vision: VisionStageResult,
        text_context: CompetitorTextContext,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[ReasoningStageResult, int, int]:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_reasoning_user_prompt(
                    vision=vision,
                    text_context=text_context,
                ),
            }
        ]
        return await self._messages_parse(
            system=reasoning_system_prompt(),
            content=content,
            output_format=ReasoningStageResult,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_cot_text_alignment",
            user_id=user_id,
            job_id=job_id,
            fallback_schema=REASONING_JSON_SCHEMA,
        )

    async def dissect_rising_star_visuals(
        self,
        *,
        sku: str,
        title: str | None,
        product_category: str | None,
        sales_growth_ratio: float | None,
        review_velocity_per_day: float,
        review_count: int,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[RisingStarVisionDissection, int, int]:
        """Deep visual audit for one money-validated Rising Star card."""

        if not images:
            raise ClaudeUpstreamError("At least one Rising Star image is required.")
        image_blocks, image_count = _encode_vision_image_blocks(
            images,
            max_images=self._settings.claude_47_max_images_per_request,
        )
        content: list[dict[str, Any]] = [
            *image_blocks,
            {
                "type": "text",
                "text": build_rising_star_vision_prompt(
                    sku=sku,
                    title=title,
                    product_category=product_category,
                    sales_growth_ratio=sales_growth_ratio,
                    review_velocity_per_day=review_velocity_per_day,
                    review_count=review_count,
                    image_count=image_count,
                ),
            },
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=rising_star_vision_system_prompt(),
            content=content,
            json_schema=RISING_STAR_VISION_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_vision_max_tokens,
            operation="claude_visual_audit_rising_star",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = RisingStarVisionDissection.model_validate(payload_json)
        except ValidationError as exc:
            raise ClaudeUpstreamError(
                "Claude Rising Star vision JSON failed schema validation."
            ) from exc
        return result, input_tokens, output_tokens

    async def analyze_money_confirmed_trigger(
        self,
        *,
        sku: str,
        title: str | None,
        marketplace: str,
        growth_ratio: float,
        recent_avg_daily_sales: float,
        baseline_avg_daily_sales: float,
        recent_window_days: int,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[MoneyConfirmedVisionResult, int, int]:
        """«Глаз Бога»: dissect current SKU photo after a money-validated sales spike."""

        if not images:
            raise ClaudeUpstreamError(
                "At least one SKU image is required for Eye-of-God Vision."
            )
        image_blocks, image_count = _encode_vision_image_blocks(
            images,
            max_images=self._settings.claude_47_max_images_per_request,
        )
        content: list[dict[str, Any]] = [
            *image_blocks,
            {
                "type": "text",
                "text": build_eye_of_god_vision_prompt(
                    sku=sku,
                    title=title,
                    marketplace=marketplace,
                    growth_ratio=growth_ratio,
                    recent_avg_daily_sales=recent_avg_daily_sales,
                    baseline_avg_daily_sales=baseline_avg_daily_sales,
                    recent_window_days=recent_window_days,
                    image_count=image_count,
                ),
            },
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=eye_of_god_vision_system_prompt(),
            content=content,
            json_schema=MONEY_CONFIRMED_VISION_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_vision_max_tokens,
            operation="claude_eye_of_god_money_trigger",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = MoneyConfirmedVisionResult.model_validate(payload_json)
        except ValidationError as exc:
            raise ClaudeUpstreamError(
                "Claude Eye-of-God Vision JSON failed schema validation."
            ) from exc
        return result, input_tokens, output_tokens

    async def analyze_competitor_card(
        self,
        *,
        card: CompetitorCardScrapeResult,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
        context_delta: Any | None = None,
    ) -> tuple[CompetitorCardDeepAnalysis, int, int]:
        """Three-vector competitor audit: Vision + reviews → frontend JSON (§78).

        ``context_delta`` — optional Semantic Filtering payload (plan §69) so
        Claude receives compressed Delta instead of the full card dump.
        """

        max_images = min(
            self._settings.claude_47_max_images_per_request,
            self._settings.competitor_audit_max_vision_images,
        )
        image_blocks, image_count = _encode_vision_image_blocks(
            images,
            max_images=max_images,
        )
        content: list[dict[str, Any]] = [
            *image_blocks,
            {
                "type": "text",
                "text": build_competitor_deep_analysis_prompt(
                    card=card,
                    image_count=image_count,
                    context_delta=context_delta,
                ),
            },
        ]
        # Vision tokens when photos present; otherwise reasoning budget for text-only.
        # Cost audit C1: text-only competitor cards use Haiku, not Opus.
        max_tokens = (
            self._settings.claude_47_vision_max_tokens
            if image_count
            else self._settings.claude_47_reasoning_max_tokens
        )
        model_override = None
        if image_count == 0:
            try:
                model_override = model_for_task(
                    ReasoningTaskKind.COMPETITOR_AUDIT,
                    simple_model=self._settings.claude_35_haiku_model,
                    deep_model=self._model,
                    has_vision=False,
                )
            except ValueError:
                model_override = self._settings.claude_35_haiku_model.strip() or None
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=competitor_deep_analysis_system_prompt(),
            content=content,
            json_schema=COMPETITOR_DEEP_ANALYSIS_JSON_SCHEMA,
            max_tokens=max_tokens,
            operation="claude_competitor_deep_analysis",
            user_id=user_id,
            job_id=job_id,
            model_override=model_override,
        )
        try:
            result = normalize_deep_analysis_card(payload_json, card=card)
        except (ValidationError, ValueError) as exc:
            raise ClaudeUpstreamError(
                f"Claude competitor deep analysis failed validation: {exc}"
            ) from exc
        return result, input_tokens, output_tokens

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
        """Plan §57: Vision OCR claims ↔ listing description dual verification."""

        if not images:
            raise ClaudeUpstreamError(
                "At least one competitor image is required for OCR cross-check."
            )
        max_images = min(
            self._settings.claude_47_max_images_per_request,
            self._settings.zero_hallucination_max_vision_images,
        )
        image_blocks, image_count = _encode_vision_image_blocks(
            images,
            max_images=max_images,
        )
        content: list[dict[str, Any]] = [
            *image_blocks,
            {
                "type": "text",
                "text": build_cross_check_user_prompt(
                    title=title,
                    description=description,
                    specs=list(specs),
                    image_count=image_count,
                    marketplace=marketplace,
                    article=article,
                ),
            },
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=cross_check_system_prompt(),
            content=content,
            json_schema=ZERO_HALLUCINATION_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_vision_max_tokens,
            operation="claude_zero_hallucination_cross_check",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = ClaudeCrossCheckPayload.model_validate(payload_json)
        except ValidationError as exc:
            raise ClaudeUpstreamError(
                "Claude Zero-Hallucination cross-check JSON failed schema validation."
            ) from exc
        return result, input_tokens, output_tokens

    async def enrich_market_gaps(
        self,
        *,
        scan_report: OracleScanReport,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[list[ClaudeGapEnrichment], int, int]:
        """Refine niche-gap alerts and infographic briefs (JSON Mode)."""

        if not scan_report.opportunities:
            raise ClaudeUpstreamError(
                "At least one market-gap opportunity is required for enrichment."
            )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_oracle_enrichment_prompt(scan_report=scan_report),
            }
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=oracle_system_prompt(),
            content=content,
            json_schema=ORACLE_ENRICHMENT_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_oracle_market_gap",
            user_id=user_id,
            job_id=job_id,
        )
        gaps_raw = payload_json.get("gaps")
        if not isinstance(gaps_raw, list) or not gaps_raw:
            raise ClaudeUpstreamError("Claude Oracle JSON missing gaps array.")
        reasoning = payload_json.get("reasoning_trace")
        if not isinstance(reasoning, str) or not reasoning.strip():
            reasoning = "Oracle enrichment completed without detailed reasoning_trace."

        enrichments: list[ClaudeGapEnrichment] = []
        known_styles = {
            gap.design_style.casefold(): gap.design_style
            for gap in scan_report.opportunities
        }
        for item in gaps_raw:
            if not isinstance(item, dict):
                continue
            style_raw = item.get("design_style")
            if not isinstance(style_raw, str):
                continue
            canonical = known_styles.get(style_raw.strip().casefold())
            if canonical is None:
                logger.warning(
                    "Oracle enrichment ignored unknown design_style=%s",
                    style_raw,
                )
                continue
            refined = item.get("refined_style_label")
            if not isinstance(refined, str) or not refined.strip():
                refined = canonical
            notification = item.get("notification_message")
            if not isinstance(notification, str) or "Обнаружена ниша" not in notification:
                notification = build_niche_notification(refined.strip())
            try:
                enrichments.append(
                    ClaudeGapEnrichment.model_validate(
                        {
                            "design_style": canonical,
                            "refined_style_label": refined.strip()[:128],
                            "notification_message": notification.strip()[:500],
                            "infographic_brief": str(
                                item.get("infographic_brief") or ""
                            ).strip()[:800],
                            "traffic_capture_tips": item.get("traffic_capture_tips")
                            or ["Сделайте акцент на визуальном стиле в первом слайде."],
                            "confidence": item.get("confidence", 0.5),
                            "reasoning_trace": reasoning.strip()[:4000],
                        }
                    )
                )
            except ValidationError:
                logger.warning(
                    "Oracle enrichment item failed validation for style=%s",
                    canonical,
                )
                continue

        if not enrichments:
            raise ClaudeUpstreamError(
                "Claude Oracle enrichment produced no valid gap items."
            )
        return enrichments, input_tokens, output_tokens

    async def enrich_strategy_plan(
        self,
        *,
        compare_report: StrategyCompareReport,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[list[ClaudeStrategyEnrichment], str, int, int]:
        """Refine killer step plan while preserving CTR-backed rationales."""

        if not compare_report.recommendations:
            raise ClaudeUpstreamError(
                "At least one killer recommendation is required for planning."
            )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_strategy_plan_prompt(compare_report=compare_report),
            }
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=strategy_system_prompt(),
            content=content,
            json_schema=STRATEGY_PLAN_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_ai_strategy_plan",
            user_id=user_id,
            job_id=job_id,
        )
        steps_raw = payload_json.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ClaudeUpstreamError("Claude AI Strategy JSON missing steps array.")

        executive = payload_json.get("executive_summary")
        if not isinstance(executive, str) or not executive.strip():
            executive = (
                f"Пошаговый killer-план из {len(compare_report.recommendations)} шагов "
                f"против лидера {compare_report.leader_sku}."
            )

        lift_by_action = {
            rec.action_type: rec.attributed_ctr_lift_pct
            for rec in compare_report.recommendations
        }
        label_by_action = {
            rec.action_type: rec.action_type.value
            for rec in compare_report.recommendations
        }
        # Prefer human labels from deterministic deltas when present.
        for delta in compare_report.deltas:
            label_by_action[delta.action_type] = delta.feature_label

        known_actions = {rec.action_type for rec in compare_report.recommendations}
        enrichments: list[ClaudeStrategyEnrichment] = []
        for item in steps_raw:
            if not isinstance(item, dict):
                continue
            action_raw = item.get("action_type")
            if not isinstance(action_raw, str):
                continue
            try:
                action = StrategyActionType(action_raw.strip())
            except ValueError:
                logger.warning(
                    "AI Strategy enrichment ignored unknown action_type=%s",
                    action_raw,
                )
                continue
            if action not in known_actions:
                logger.warning(
                    "AI Strategy enrichment ignored unexpected action_type=%s",
                    action.value,
                )
                continue
            refined = item.get("refined_title")
            if not isinstance(refined, str) or not refined.strip():
                refined = action.value
            instruction = item.get("instruction")
            if not isinstance(instruction, str) or not instruction.strip():
                instruction = "Примените изменение по образцу лидера ниши."
            rationale = item.get("rationale")
            if not isinstance(rationale, str) or "выше CTR" not in rationale:
                rationale = build_ctr_rationale(
                    feature_label=label_by_action.get(action, action.value),
                    ctr_lift_pct=lift_by_action.get(action, 1.0),
                )
            impact = item.get("expected_impact")
            if not isinstance(impact, str) or not impact.strip():
                impact = (
                    f"Ожидаемый вклад в CTR: ≈{lift_by_action.get(action, 0):.0f}% "
                    f"от преимущества лидера."
                )
            try:
                enrichments.append(
                    ClaudeStrategyEnrichment.model_validate(
                        {
                            "action_type": action,
                            "refined_title": refined.strip()[:200],
                            "instruction": instruction.strip()[:800],
                            "rationale": rationale.strip()[:500],
                            "expected_impact": impact.strip()[:300],
                            "confidence": item.get("confidence", 0.5),
                        }
                    )
                )
            except ValidationError:
                logger.warning(
                    "AI Strategy enrichment item failed validation for action=%s",
                    action.value,
                )
                continue

        if not enrichments:
            raise ClaudeUpstreamError(
                "Claude AI Strategy enrichment produced no valid steps."
            )
        return enrichments, executive.strip()[:800], input_tokens, output_tokens

    async def generate_ab_hypotheses(
        self,
        *,
        product: AbProductBrief,
        user_id: UUID | None = None,
        experiment_id: UUID | None = None,
    ) -> tuple[tuple[AbVariantHypothesis, ...], int, int]:
        """Generate exactly three main-card creative hypotheses for A/B testing."""

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_ab_hypotheses_prompt(product=product),
            }
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=ab_system_prompt(),
            content=content,
            json_schema=AB_HYPOTHESES_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_ab_test_hypotheses",
            user_id=user_id,
            job_id=experiment_id,
        )
        variants_raw = payload_json.get("variants")
        if not isinstance(variants_raw, list) or len(variants_raw) < 3:
            raise ClaudeUpstreamError(
                "Claude A/B JSON must include exactly 3 variants."
            )
        try:
            hypotheses = normalize_hypotheses(variants_raw)
        except (ValidationError, ValueError) as exc:
            raise ClaudeUpstreamError(
                f"Claude A/B hypotheses failed validation: {exc}"
            ) from exc
        return hypotheses, input_tokens, output_tokens

    async def analyze_competitor_pains(
        self,
        *,
        request: PainAnalysisRequest,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[PainAnalysisResult, int, int]:
        """Filter junk competitor negatives and produce pain-closing content."""

        if not request.raw_negative_reviews:
            raise ClaudeUpstreamError(
                "At least one negative review is required for pain analysis."
            )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_pain_analysis_prompt(request=request),
            }
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=pain_analysis_system_prompt(),
            content=content,
            json_schema=PAIN_ANALYSIS_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_pain_analysis",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = normalize_claude_pain_result(
                payload_json,
                model_name=self._model,
            )
        except (ValidationError, ValueError) as exc:
            raise ClaudeUpstreamError(
                f"Claude pain analysis failed validation: {exc}"
            ) from exc
        return result, input_tokens, output_tokens

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
        """Plan §59: propose corrected card text after Fail-Safe sandbox errors."""

        if not issues:
            raise ClaudeUpstreamError("No validation issues provided for export auto-fix.")
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": build_export_fix_prompt(
                    platform=platform,
                    title=title,
                    description=description,
                    characteristics=characteristics,
                    issues=issues,
                    product_category=product_category,
                    extras=extras,
                    title_max=title_max,
                    description_max=description_max,
                    characteristics_max=characteristics_max,
                    characteristic_max_length=characteristic_max_length,
                ),
            }
        ]
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=export_fix_system_prompt(),
            content=content,
            json_schema=EXPORT_FIX_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_export_fail_safe_fix",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = normalize_export_fix_payload(
                payload_json,
                model_name=self._model,
            )
        except (ValidationError, ValueError) as exc:
            raise ClaudeUpstreamError(
                f"Claude export fail-safe fix failed validation: {exc}"
            ) from exc
        return result, input_tokens, output_tokens

    async def _messages_parse(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        output_format: type[BaseModel],
        max_tokens: int,
        operation: str,
        user_id: UUID | None,
        job_id: UUID | None,
        fallback_schema: dict[str, Any],
    ) -> tuple[Any, int, int]:
        """Prefer official SDK parse; fall back to schema-constrained create.

        Haiku / non-adaptive models skip Opus-only adaptive thinking and use
        the JSON path. Timeouts and connection errors are retried so a slow
        Anthropic edge never bubbles as an unhandled crash into the API process.
        """

        if not self._adaptive:
            payload_json, input_tokens, output_tokens = await self._messages_json(
                system=system,
                content=content,
                json_schema=fallback_schema,
                max_tokens=max_tokens,
                operation=operation,
                user_id=user_id,
                job_id=job_id,
            )
            try:
                return (
                    output_format.model_validate(payload_json),
                    input_tokens,
                    output_tokens,
                )
            except ValidationError as validation_exc:
                raise ClaudeUpstreamError(
                    "Claude JSON failed schema validation."
                ) from validation_exc

        attempts = self._settings.claude_47_max_retries + 1
        last_transport: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._sdk.messages.parse(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=_system_blocks_with_cache(harden_system_prompt(system)),
                    messages=[{"role": "user", "content": content}],
                    thinking={"type": "adaptive"},
                    output_config={"effort": self._settings.claude_47_effort},
                    output_format=output_format,
                )
            except (APITimeoutError, APIConnectionError) as exc:
                last_transport = exc
                if attempt >= attempts:
                    await self._record_usage(
                        operation=operation,
                        input_tokens=0,
                        output_tokens=0,
                        user_id=user_id,
                        job_id=job_id,
                        usage=None,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        status="Timeout" if isinstance(exc, APITimeoutError) else "Error",
                    )
                    raise ClaudeUpstreamError(
                        "Claude request failed after retries."
                    ) from exc
                await asyncio.sleep(self._retry_delay(attempt, None))
                continue
            except APIStatusError as exc:
                # Transient upstream / rate-limit: retry before failing the job.
                if (
                    exc.status_code in TRANSIENT_HTTP_CODES
                    and attempt < attempts
                ):
                    await asyncio.sleep(self._retry_delay(attempt, None))
                    continue
                # Older SDK / transitional accounts may reject parse; use JSON schema path.
                if exc.status_code in {400, 404, 422}:
                    payload_json, input_tokens, output_tokens = await self._messages_json(
                        system=system,
                        content=content,
                        json_schema=fallback_schema,
                        max_tokens=max_tokens,
                        operation=operation,
                        user_id=user_id,
                        job_id=job_id,
                    )
                    try:
                        return (
                            output_format.model_validate(payload_json),
                            input_tokens,
                            output_tokens,
                        )
                    except ValidationError as validation_exc:
                        raise ClaudeUpstreamError(
                            "Claude JSON failed schema validation."
                        ) from validation_exc
                await self._record_usage(
                    operation=operation,
                    input_tokens=0,
                    output_tokens=0,
                    user_id=user_id,
                    job_id=job_id,
                    usage=None,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    status="Error",
                )
                raise ClaudeUpstreamError(
                    f"Claude API error {exc.status_code}: {str(exc)[:500]}"
                ) from exc
            except Exception as exc:  # noqa: BLE001 — map unknown SDK failures
                await self._record_usage(
                    operation=operation,
                    input_tokens=0,
                    output_tokens=0,
                    user_id=user_id,
                    job_id=job_id,
                    usage=None,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    status="Error",
                )
                raise ClaudeUpstreamError(
                    f"Claude SDK unexpected failure: {type(exc).__name__}"
                ) from exc

            if response.parsed_output is None:
                await self._record_usage(
                    operation=operation,
                    input_tokens=0,
                    output_tokens=0,
                    user_id=user_id,
                    job_id=job_id,
                    usage=None,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    status="Error",
                )
                raise ClaudeUpstreamError(
                    "Claude parse returned empty structured output."
                )
            usage = getattr(response, "usage", None)
            input_tokens = _safe_token_count(getattr(usage, "input_tokens", None))
            output_tokens = _safe_token_count(getattr(usage, "output_tokens", None))
            await self._record_usage(
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                user_id=user_id,
                job_id=job_id,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="Success",
            )
            return response.parsed_output, input_tokens, output_tokens

        raise ClaudeUpstreamError(
            "Claude request failed after retries."
        ) from last_transport

    async def _messages_json(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        json_schema: dict[str, Any],
        max_tokens: int,
        operation: str,
        user_id: UUID | None,
        job_id: UUID | None,
        model_override: str | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        cache_key = self._analytics_cache_key(
            system=system,
            content=content,
            json_schema=json_schema,
            operation=operation,
            model_override=model_override,
        )
        cached = await self._read_analytics_cache(cache_key)
        if cached is not None:
            payload_hit = cached.get("payload")
            if isinstance(payload_hit, dict):
                logger.info(
                    "Claude analytics cache hit operation=%s model=%s",
                    operation,
                    model_override or self._model,
                )
                return payload_hit, 0, 0

        effective_model = (model_override or self._model).strip() or self._model
        adaptive = model_supports_adaptive_thinking(effective_model)

        extra_headers: dict[str, str] = {}
        beta = self._settings.claude_47_structured_outputs_beta.strip()
        if beta and adaptive:
            extra_headers["anthropic-beta"] = beta

        hardened = harden_system_prompt(system)
        # Anthropic prompt caching (C3): ephemeral cache on stable system blocks.
        system_blocks = _system_blocks_with_cache(hardened)
        if adaptive:
            # Opus 4.7 rejects temperature/top_p/top_k and token-budget thinking.
            create_kwargs: dict[str, Any] = {
                "model": effective_model,
                "max_tokens": max_tokens,
                "thinking": {"type": "adaptive"},
                "system": system_blocks,
                "messages": [{"role": "user", "content": content}],
                "output_config": {
                    "effort": self._settings.claude_47_effort,
                    "format": {
                        "type": "json_schema",
                        "schema": json_schema,
                    },
                },
            }
        else:
            # Claude 3.5 Haiku: classic Messages API + JSON-in-text contract.
            haiku_system = (
                f"{hardened}\n\n"
                "Respond with a single JSON object only (no markdown fences). "
                "The JSON must match the required schema."
            )
            create_kwargs = {
                "model": effective_model,
                "max_tokens": max_tokens,
                "temperature": self._settings.claude_47_temperature,
                "system": _system_blocks_with_cache(haiku_system),
                "messages": [{"role": "user", "content": content}],
            }

        started = time.perf_counter()
        response = await self._messages_create_with_retry(
            create_kwargs=create_kwargs,
            extra_headers=extra_headers or None,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            text = _extract_sdk_text_content(getattr(response, "content", None))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            await self._record_usage(
                operation=operation,
                input_tokens=0,
                output_tokens=0,
                user_id=user_id,
                job_id=job_id,
                usage=None,
                duration_ms=duration_ms,
                status="Error",
                model_name=effective_model,
            )
            raise ClaudeUpstreamError("Unexpected Anthropic response shape.") from exc
        if not isinstance(text, str) or not text.strip():
            await self._record_usage(
                operation=operation,
                input_tokens=0,
                output_tokens=0,
                user_id=user_id,
                job_id=job_id,
                usage=None,
                duration_ms=duration_ms,
                status="Error",
                model_name=effective_model,
            )
            raise ClaudeUpstreamError("Anthropic returned empty text.")

        try:
            parsed = extract_json_object(text)
        except (ValueError, TypeError) as exc:
            await self._record_usage(
                operation=operation,
                input_tokens=0,
                output_tokens=0,
                user_id=user_id,
                job_id=job_id,
                usage=None,
                duration_ms=duration_ms,
                status="Error",
                model_name=effective_model,
            )
            raise ClaudeUpstreamError("Anthropic response is not valid JSON.") from exc

        usage_obj = getattr(response, "usage", None)
        input_tokens = _safe_token_count(getattr(usage_obj, "input_tokens", None))
        output_tokens = _safe_token_count(getattr(usage_obj, "output_tokens", None))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        await self._record_usage(
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            user_id=user_id,
            job_id=job_id,
            usage=usage,
            duration_ms=duration_ms,
            status="Success",
            model_name=effective_model,
        )
        await self._write_analytics_cache(
            cache_key,
            {
                "payload": parsed,
                "model": effective_model,
                "operation": operation,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_hit": False,
            },
        )
        return parsed, input_tokens, output_tokens

    def _analytics_cache_key(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        json_schema: dict[str, Any],
        operation: str,
        model_override: str | None = None,
    ) -> str | None:
        if self._analytics_cache is None:
            return None
        try:
            fingerprint = fingerprint_messages_request(
                model_name=(model_override or self._model),
                system=system,
                content=content,
                json_schema=json_schema,
                operation=operation,
            )
            return redis_analytics_key(
                task_kind=self._analytics_task_kind,
                model_name=(model_override or self._model),
                fingerprint=fingerprint,
            )
        except (TypeError, ValueError):
            logger.debug(
                "Skipped analytics cache key for operation=%s",
                operation,
                exc_info=True,
            )
            return None

    async def _read_analytics_cache(
        self, cache_key: str | None
    ) -> dict[str, Any] | None:
        if cache_key is None or self._analytics_cache is None:
            return None
        try:
            return await self._analytics_cache.get(cache_key)
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning(
                "Analytics cache read failed key=%s", cache_key, exc_info=True
            )
            return None

    async def _write_analytics_cache(
        self, cache_key: str | None, payload: dict[str, Any]
    ) -> None:
        if cache_key is None or self._analytics_cache is None:
            return
        try:
            await self._analytics_cache.set(
                cache_key,
                payload,
                self._analytics_cache_ttl_seconds,
            )
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning(
                "Analytics cache write failed key=%s", cache_key, exc_info=True
            )

    async def _messages_create_with_retry(
        self,
        *,
        create_kwargs: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Send Messages.create via the sole SDK transport with transient retries."""

        attempts = self._settings.claude_47_max_retries + 1
        last_error: Exception | None = None
        call_kwargs = dict(create_kwargs)
        if extra_headers:
            call_kwargs["extra_headers"] = extra_headers
        for attempt in range(1, attempts + 1):
            try:
                return await self._sdk.messages.create(**call_kwargs)
            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._retry_delay(attempt, None))
            except APIStatusError as exc:
                last_error = exc
                if (
                    exc.status_code in TRANSIENT_HTTP_CODES
                    and attempt < attempts
                ):
                    retry_after = _retry_after_from_status_error(exc)
                    await asyncio.sleep(self._retry_delay(attempt, retry_after))
                    continue
                raise ClaudeUpstreamError(
                    f"Claude API error {exc.status_code}: {str(exc)[:500]}"
                ) from exc
        raise ClaudeUpstreamError(
            "Claude request failed after retries."
        ) from last_error

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return min(parsed, 15.0)
            except ValueError:
                logger.debug("Ignoring non-numeric Retry-After: %s", retry_after)
        return min(
            self._settings.claude_47_base_retry_delay_seconds * (2 ** (attempt - 1))
            + random.uniform(0.0, 0.35),
            15.0,
        )

    async def _record_usage(
        self,
        *,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        user_id: UUID | None,
        job_id: UUID | None,
        usage: dict[str, Any] | None,
        duration_ms: int | None = None,
        status: str = "Success",
        model_name: str | None = None,
    ) -> None:
        total_tokens = input_tokens + output_tokens
        total_cost = (
            Decimal(input_tokens)
            / Decimal(1000)
            * self._settings.claude_47_input_1k_tokens_cost_usd
            + Decimal(output_tokens)
            / Decimal(1000)
            * self._settings.claude_47_output_1k_tokens_cost_usd
        )
        units = max(total_tokens, 1)
        resolved_model = (model_name or self._model).strip() or self._model
        # Only link generation_jobs FK when the caller job_id is a GenerationJob
        # (export fail-safe / zero-hallucination). Other Claude workflows
        # (CoT, pain, oracle, audits) correlate via task_id only (audit C5).
        link_generation_job = operation in _GENERATION_JOB_LINKED_OPERATIONS
        generation_job_id = job_id if link_generation_job else None
        meta: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "task_id": str(job_id) if job_id else None,
            "anthropic_usage": usage,
        }
        if generation_job_id is not None:
            meta["generation_job_id"] = str(generation_job_id)
        if job_id is not None and operation in {
            "claude_vision_triggers",
            "claude_cot_text_alignment",
        }:
            meta["claude_reasoning_job_id"] = str(job_id)
        await record_api_usage_cost(
            provider="anthropic",
            model_name=resolved_model,
            operation=operation,
            units=units,
            unit_cost_usd=total_cost / Decimal(units),
            total_cost_usd=total_cost,
            user_id=user_id,
            generation_job_id=generation_job_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            duration_ms=duration_ms,
            task_id=job_id,
            metadata=meta,
        )


def _system_blocks_with_cache(system_text: str) -> list[dict[str, Any]]:
    """Wrap system prompt as Anthropic content blocks with ephemeral prompt cache."""

    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _safe_token_count(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _encode_vision_image_blocks(
    images: tuple[tuple[bytes, str], ...],
    *,
    max_images: int,
) -> tuple[list[dict[str, Any]], int]:
    """Limit Vision payload size and free raw bytes immediately after base64 encode.

    Returns ``(image_content_blocks, selected_count)``. Unused images beyond
    ``max_images`` are never normalized or encoded.
    """

    limit = max(0, int(max_images))
    blocks: list[dict[str, Any]] = []
    for index, (raw_bytes, mime_type) in enumerate(images):
        if index >= limit:
            break
        normalized, media_type = normalize_image_for_claude(
            raw_bytes,
            media_type=mime_type,
        )
        # Drop the caller slice reference as soon as normalized bytes exist.
        del raw_bytes
        encoded = base64.b64encode(normalized).decode("ascii")
        del normalized
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            }
        )
    return blocks, len(blocks)


def _retry_after_from_status_error(exc: APIStatusError) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    return str(value) if value is not None else None


def _extract_sdk_text_content(content: object) -> str:
    """Return the first text block from an Anthropic SDK Message.content list."""

    if not isinstance(content, list) or not content:
        raise ValueError("Missing content blocks.")
    texts: list[str] = []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type is None and isinstance(block, dict):
            block_type = block.get("type")
            text = block.get("text")
        else:
            text = getattr(block, "text", None)
        if block_type == "thinking":
            continue
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if not texts:
        raise ValueError("No text content block in Anthropic response.")
    return texts[0]


def _extract_text_content(content: object) -> str:
    """Return the first text block, ignoring Anthropic thinking blocks."""

    if not isinstance(content, list) or not content:
        raise ValueError("Missing content blocks.")
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if not texts:
        raise ValueError("No text content block in Anthropic response.")
    return texts[0]
