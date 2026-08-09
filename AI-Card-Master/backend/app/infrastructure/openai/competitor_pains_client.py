"""OpenAI (or OpenAI-compatible local GPU) adapter for competitor pains analysis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from decimal import Decimal
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.prompt_safety import fence_untrusted_text, harden_system_prompt
from app.domain.competitor_pains_llm import (
    CompetitorPainsAnalysisRequest,
    CompetitorPainsAnalysisResult,
    CompetitorPainsConfigurationError,
    CompetitorPainsLlmProvider,
    CompetitorPainsUpstreamError,
    build_competitor_pains_user_prompt,
    competitor_pains_system_prompt,
    normalize_competitor_pains_payload,
)
from app.infrastructure.openai.seo_text_client import resolve_openai_api_key
from app.services.api_usage_costs import record_api_usage_cost

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_DEFAULT_INPUT_COST_PER_1K = Decimal("0.0004")
_DEFAULT_OUTPUT_COST_PER_1K = Decimal("0.0016")


class OpenAiCompetitorPainsClient:
    """Call OpenAI ``/v1/chat/completions`` (also works with local OpenAI-compatible nodes)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        base_retry_delay_seconds: float = 0.35,
        require_api_key: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key_override = api_key
        self._model = (model or os.getenv("LLM_MODEL", "gpt-4.1-mini")).strip()
        self._base_url = (
            base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com")
        ).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, int(max_retries))
        self._base_retry_delay_seconds = base_retry_delay_seconds
        self._require_api_key = require_api_key
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(
                max_connections=40,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            http2=True,
        )

    @property
    def provider_name(self) -> str:
        return CompetitorPainsLlmProvider.OPENAI.value

    @property
    def model_name(self) -> str:
        return self._model

    def _resolve_api_key(self) -> str:
        if self._api_key_override is not None:
            cleaned = self._api_key_override.strip()
            if cleaned:
                return cleaned
            if not self._require_api_key:
                return "local"
            raise CompetitorPainsConfigurationError(
                "OPENAI_API_KEY is not configured. Set OPENAI_API_KEY "
                "(or LLM_API_KEY), or point LLM_BASE_URL at a local GPU node."
            )
        try:
            return resolve_openai_api_key()
        except Exception as exc:
            if not self._require_api_key:
                return "local"
            raise CompetitorPainsConfigurationError(str(exc)) from exc

    def ensure_configured(self) -> None:
        self._resolve_api_key()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def analyze_negative_reviews(
        self,
        request: CompetitorPainsAnalysisRequest,
    ) -> CompetitorPainsAnalysisResult:
        api_key = self._resolve_api_key()
        system = harden_system_prompt(competitor_pains_system_prompt())
        user_raw = build_competitor_pains_user_prompt(request)
        user = fence_untrusted_text(
            user_raw,
            label="competitor_negative_reviews",
            max_length=40_000,
        )
        payload = {
            "model": self._model,
            "temperature": 0.2,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = await self._post_with_retry(
            endpoint="/v1/chat/completions",
            headers=headers,
            payload=payload,
        )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise CompetitorPainsUpstreamError(
                "Unexpected OpenAI response shape."
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise CompetitorPainsUpstreamError("OpenAI returned empty text.")

        usage = body.get("usage") if isinstance(body, dict) else None
        in_tok = _safe_int(usage.get("prompt_tokens") if isinstance(usage, dict) else 0)
        out_tok = _safe_int(
            usage.get("completion_tokens") if isinstance(usage, dict) else 0
        )
        parsed = _parse_json_object(content)
        try:
            result = normalize_competitor_pains_payload(
                parsed,
                provider=CompetitorPainsLlmProvider.OPENAI,
                model_name=self._model,
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        except ValidationError as exc:
            raise CompetitorPainsUpstreamError(
                "OpenAI response failed competitor-pains schema."
            ) from exc

        await _record_openai_usage(
            model_name=self._model,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
        return result

    async def _post_with_retry(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        attempts = self._max_retries + 1
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
                    raise CompetitorPainsUpstreamError(
                        f"OpenAI API error {response.status_code}: "
                        f"{response.text[:500]}"
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
        raise CompetitorPainsUpstreamError(
            "OpenAI request failed after retries."
        ) from last_error

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after)
                    if parsed > 0:
                        return min(parsed, 10.0)
                except ValueError:
                    logger.debug("Ignoring non-numeric Retry-After: %s", retry_after)
        return min(
            self._base_retry_delay_seconds * (2 ** (attempt - 1))
            + random.uniform(0.0, 0.35),
            10.0,
        )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    raw = raw_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompetitorPainsUpstreamError(
            "OpenAI response is not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise CompetitorPainsUpstreamError("OpenAI JSON root must be an object.")
    return payload


def _safe_int(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


async def _record_openai_usage(
    *,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    in_cost = (Decimal(input_tokens) / Decimal(1000)) * _DEFAULT_INPUT_COST_PER_1K
    out_cost = (Decimal(output_tokens) / Decimal(1000)) * _DEFAULT_OUTPUT_COST_PER_1K
    total = in_cost + out_cost
    await record_api_usage_cost(
        provider="openai",
        model_name=model_name,
        operation="competitor_pains_analyze",
        units=max(input_tokens + output_tokens, 1),
        unit_cost_usd=(total / Decimal(max(input_tokens + output_tokens, 1)))
        if (input_tokens + output_tokens) > 0
        else Decimal("0"),
        total_cost_usd=total,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status="Success",
        metadata={"feature": "competitor_pains_llm"},
    )
