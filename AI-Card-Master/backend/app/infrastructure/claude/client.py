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
from pydantic import ValidationError

from app.core.config import Settings, get_settings
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
from app.domain.visual_audit import (
    RISING_STAR_VISION_JSON_SCHEMA,
    RisingStarVisionDissection,
    build_rising_star_vision_prompt,
    rising_star_vision_system_prompt,
)
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
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
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
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=vision_system_prompt(),
            content=content,
            json_schema=VISION_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_vision_max_tokens,
            operation="claude_vision_triggers",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = VisionStageResult.model_validate(payload_json)
        except ValidationError as exc:
            raise ClaudeUpstreamError(
                "Claude Vision JSON failed schema validation."
            ) from exc
        return result, input_tokens, output_tokens

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
        payload_json, input_tokens, output_tokens = await self._messages_json(
            system=reasoning_system_prompt(),
            content=content,
            json_schema=REASONING_JSON_SCHEMA,
            max_tokens=self._settings.claude_47_reasoning_max_tokens,
            operation="claude_cot_text_alignment",
            user_id=user_id,
            job_id=job_id,
        )
        try:
            result = ReasoningStageResult.model_validate(payload_json)
        except ValidationError as exc:
            raise ClaudeUpstreamError(
                "Claude reasoning JSON failed schema validation."
            ) from exc
        return result, input_tokens, output_tokens

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
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
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

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": self._settings.claude_47_temperature,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": json_schema,
                }
            },
        }
        response = await self._post_with_retry(
            endpoint="/v1/messages",
            headers=headers,
            payload=payload,
        )
        try:
            body = response.json()
            text = body["content"][0]["text"]
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
