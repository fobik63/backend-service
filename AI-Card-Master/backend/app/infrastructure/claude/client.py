"""Anthropic Claude 4.7 Opus client: Vision API + JSON Mode + CoT stages."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
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
from app.domain.visual_audit import (
    RISING_STAR_VISION_JSON_SCHEMA,
    RisingStarVisionDissection,
    build_rising_star_vision_prompt,
    rising_star_vision_system_prompt,
)
from app.infrastructure.claude.image_normalize import normalize_image_for_claude
from app.services.api_usage_costs import record_api_usage_cost
from app.services.infographic_service import TRANSIENT_HTTP_CODES

logger = logging.getLogger(__name__)


class ClaudeIntegrationError(Exception):
    """Base Claude 4.7 integration failure."""


class ClaudeConfigurationError(ClaudeIntegrationError):
    """Missing or invalid Claude API settings."""


class ClaudeUpstreamError(ClaudeIntegrationError):
    """Upstream Anthropic request/response cannot be trusted."""


class Claude47VisionClient:
    """Async Anthropic Messages client for Vision + structured JSON CoT."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        api_key = self._settings.claude_47_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise ClaudeConfigurationError(
                "CLAUDE_47_API_KEY is required for Claude Vision reasoning."
            )
        self._api_key = api_key.get_secret_value().strip()
        self._model = self._settings.claude_47_model.strip()
        if not self._model:
            raise ClaudeConfigurationError("CLAUDE_47_MODEL must not be empty.")
        self._sdk = AsyncAnthropic(
            api_key=self._api_key,
            base_url=self._settings.claude_47_base_url.rstrip("/"),
            timeout=self._settings.claude_47_timeout_seconds,
            max_retries=0,
        )
        # Legacy httpx path kept for deterministic retry/Retry-After handling.
        self._client = httpx.AsyncClient(
            base_url=self._settings.claude_47_base_url.rstrip("/"),
            timeout=httpx.Timeout(self._settings.claude_47_timeout_seconds),
            limits=httpx.Limits(
                max_connections=self._settings.claude_47_max_connections,
                max_keepalive_connections=self._settings.claude_47_max_keepalive_connections,
                keepalive_expiry=30.0,
            ),
            http2=True,
        )

    @property
    def model_name(self) -> str:
        return self._model

    async def aclose(self) -> None:
        await self._client.aclose()
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
        max_images = self._settings.claude_47_max_images_per_request
        selected = images[:max_images]
        content: list[dict[str, Any]] = []
        for image_bytes, mime_type in selected:
            normalized, media_type = normalize_image_for_claude(
                image_bytes,
                media_type=mime_type,
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(normalized).decode("ascii"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": build_vision_user_prompt(
                    product_category=product_category,
                    image_count=len(selected),
                ),
            }
        )
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
        max_images = self._settings.claude_47_max_images_per_request
        selected = images[:max_images]
        content: list[dict[str, Any]] = []
        for image_bytes, mime_type in selected:
            normalized, media_type = normalize_image_for_claude(
                image_bytes,
                media_type=mime_type,
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(normalized).decode("ascii"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": build_rising_star_vision_prompt(
                    sku=sku,
                    title=title,
                    product_category=product_category,
                    sales_growth_ratio=sales_growth_ratio,
                    review_velocity_per_day=review_velocity_per_day,
                    review_count=review_count,
                    image_count=len(selected),
                ),
            }
        )
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
        max_images = self._settings.claude_47_max_images_per_request
        selected = images[:max_images]
        content: list[dict[str, Any]] = []
        for image_bytes, mime_type in selected:
            normalized, media_type = normalize_image_for_claude(
                image_bytes,
                media_type=mime_type,
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(normalized).decode("ascii"),
                    },
                }
            )
        content.append(
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
                    image_count=len(selected),
                ),
            }
        )
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
    ) -> tuple[CompetitorCardDeepAnalysis, int, int]:
        """Three-vector competitor audit: Vision + reviews → frontend JSON (§78)."""

        max_images = min(
            self._settings.claude_47_max_images_per_request,
            self._settings.competitor_audit_max_vision_images,
        )
        selected = images[:max_images]
        content: list[dict[str, Any]] = []
        for image_bytes, mime_type in selected:
            normalized, media_type = normalize_image_for_claude(
                image_bytes,
                media_type=mime_type,
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(normalized).decode("ascii"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": build_competitor_deep_analysis_prompt(
                    card=card,
                    image_count=len(selected),
                ),
            }
        )
        # Vision tokens when photos present; otherwise reasoning budget for text-only.
        max_tokens = (
            self._settings.claude_47_vision_max_tokens
            if selected
            else self._settings.claude_47_reasoning_max_tokens
        )
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=competitor_deep_analysis_system_prompt(),
            content=content,
            json_schema=COMPETITOR_DEEP_ANALYSIS_JSON_SCHEMA,
            max_tokens=max_tokens,
            operation="claude_competitor_deep_analysis",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = normalize_deep_analysis_card(payload_json, card=card)
        except (ValidationError, ValueError) as exc:
            raise ClaudeUpstreamError(
                f"Claude competitor deep analysis failed validation: {exc}"
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

        Timeouts and connection errors are retried so a slow Anthropic edge
        never bubbles as an unhandled crash into the API process.
        """

        attempts = self._settings.claude_47_max_retries + 1
        last_transport: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._sdk.messages.parse(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=harden_system_prompt(system),
                    messages=[{"role": "user", "content": content}],
                    thinking={"type": "adaptive"},
                    output_config={"effort": self._settings.claude_47_effort},
                    output_format=output_format,
                )
            except (APITimeoutError, APIConnectionError) as exc:
                last_transport = exc
                if attempt >= attempts:
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
                raise ClaudeUpstreamError(
                    f"Claude API error {exc.status_code}: {str(exc)[:500]}"
                ) from exc
            except Exception as exc:  # noqa: BLE001 — map unknown SDK failures
                raise ClaudeUpstreamError(
                    f"Claude SDK unexpected failure: {type(exc).__name__}"
                ) from exc

            if response.parsed_output is None:
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
    ) -> tuple[dict[str, Any], int, int]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._settings.claude_47_api_version,
            "content-type": "application/json",
        }
        beta = self._settings.claude_47_structured_outputs_beta.strip()
        if beta:
            headers["anthropic-beta"] = beta

        # Opus 4.7 rejects temperature/top_p/top_k and token-budget thinking.
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "thinking": {"type": "adaptive"},
            "system": harden_system_prompt(system),
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "effort": self._settings.claude_47_effort,
                "format": {
                    "type": "json_schema",
                    "schema": json_schema,
                },
            },
        }
        response = await self._post_with_retry(
            endpoint="/v1/messages",
            headers=headers,
            payload=payload,
        )
        try:
            body = response.json()
            text = _extract_text_content(body.get("content"))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ClaudeUpstreamError("Unexpected Anthropic response shape.") from exc
        if not isinstance(text, str) or not text.strip():
            raise ClaudeUpstreamError("Anthropic returned empty text.")

        try:
            parsed = extract_json_object(text)
        except (ValueError, TypeError) as exc:
            raise ClaudeUpstreamError("Anthropic response is not valid JSON.") from exc

        usage = body.get("usage") if isinstance(body, dict) else None
        input_tokens = _safe_token_count(
            usage.get("input_tokens") if isinstance(usage, dict) else None
        )
        output_tokens = _safe_token_count(
            usage.get("output_tokens") if isinstance(usage, dict) else None
        )
        await self._record_usage(
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            user_id=user_id,
            job_id=job_id,
            usage=usage if isinstance(usage, dict) else None,
        )
        return parsed, input_tokens, output_tokens

    async def _post_with_retry(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        attempts = self._settings.claude_47_max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(
                    endpoint, headers=headers, json=payload
                )
                if response.status_code in TRANSIENT_HTTP_CODES and attempt < attempts:
                    await asyncio.sleep(self._retry_delay(attempt, response))
                    continue
                if response.is_error:
                    raise ClaudeUpstreamError(
                        f"Claude API error {response.status_code}: {response.text[:500]}"
                    )
                return response
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._retry_delay(attempt, None))
        raise ClaudeUpstreamError(
            "Claude request failed after retries."
        ) from last_error

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
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
        await record_api_usage_cost(
            provider="anthropic",
            model_name=self._model,
            operation=operation,
            units=units,
            unit_cost_usd=total_cost / Decimal(units),
            total_cost_usd=total_cost,
            user_id=user_id,
            generation_job_id=None,
            metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "claude_reasoning_job_id": str(job_id) if job_id else None,
                "anthropic_usage": usage,
            },
        )


def _safe_token_count(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


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
