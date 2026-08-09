"""OpenAI chat-completions adapter for marketplace SEO copy."""

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
from app.domain.seo_text import (
    SEO_SYSTEM_PROMPT,
    SeoTextConfigurationError,
    SeoTextContent,
    SeoTextGenerateRequest,
    SeoTextUpstreamError,
    SeoTokenUsage,
    description_limit_for,
)
from app.services.api_usage_costs import record_api_usage_cost

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Approximate public GPT-4.1-mini list prices (USD / 1K tokens) for cost analytics.
_DEFAULT_INPUT_COST_PER_1K = Decimal("0.0004")
_DEFAULT_OUTPUT_COST_PER_1K = Decimal("0.0016")


def resolve_openai_api_key() -> str:
    """Resolve OpenAI credentials: ``OPENAI_API_KEY`` then ``LLM_API_KEY``."""

    for env_name in ("OPENAI_API_KEY", "LLM_API_KEY"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    raise SeoTextConfigurationError(
        "OPENAI_API_KEY is not configured. Set OPENAI_API_KEY (or LLM_API_KEY) "
        "to enable SEO text generation."
    )


class OpenAiSeoTextClient:
    """Call OpenAI ``/v1/chat/completions`` and parse strict SEO JSON."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        base_retry_delay_seconds: float = 0.35,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # Lazy key resolution in ``generate`` so missing credentials map to
        # a clean API 503 instead of failing FastAPI dependency injection.
        self._api_key_override = api_key
        self._model = (model or os.getenv("LLM_MODEL", "gpt-4.1-mini")).strip()
        self._base_url = (
            base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com")
        ).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, int(max_retries))
        self._base_retry_delay_seconds = base_retry_delay_seconds
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

    def _resolve_api_key(self) -> str:
        if self._api_key_override is not None:
            cleaned = self._api_key_override.strip()
            if not cleaned:
                raise SeoTextConfigurationError(
                    "OPENAI_API_KEY is not configured. Set OPENAI_API_KEY "
                    "(or LLM_API_KEY) to enable SEO text generation."
                )
            return cleaned
        return resolve_openai_api_key()

    def ensure_configured(self) -> None:
        """Raise ``SeoTextConfigurationError`` when the API key is missing."""

        self._resolve_api_key()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(
        self, request: SeoTextGenerateRequest
    ) -> tuple[SeoTextContent, SeoTokenUsage]:
        api_key = self._resolve_api_key()
        payload = {
            "model": self._model,
            "temperature": 0.55,
            "max_tokens": 2800,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _build_user_prompt(request)},
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
            raise SeoTextUpstreamError("Unexpected OpenAI response shape.") from exc
        if not isinstance(content, str) or not content.strip():
            raise SeoTextUpstreamError("OpenAI returned empty text.")

        usage = _parse_usage(body.get("usage"))
        parsed = _parse_seo_content(content, request=request)
        await _record_openai_usage(
            model_name=self._model,
            usage=usage,
            user_metadata={"target_platform": request.target_platform.value},
        )
        return parsed, usage

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
                    raise SeoTextUpstreamError(
                        f"OpenAI API error {response.status_code}: {response.text[:500]}"
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
        raise SeoTextUpstreamError(
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


def _system_prompt() -> str:
    return harden_system_prompt(
        f"{SEO_SYSTEM_PROMPT}. Отвечай только валидным JSON без markdown."
    )


def _build_user_prompt(request: SeoTextGenerateRequest) -> str:
    limit = description_limit_for(request.target_platform)
    features_json = json.dumps(dict(request.features), ensure_ascii=False, default=str)
    fenced_title = fence_untrusted_text(request.title, label="title")
    fenced_category = fence_untrusted_text(request.category, label="category")
    fenced_features = fence_untrusted_text(features_json, label="features", max_length=8000)
    platform_label = (
        "Wildberries" if request.target_platform.value == "wb" else "Ozon"
    )
    return (
        f"Сгенерируй SEO-контент карточки товара для {platform_label}. "
        "Верни строго JSON вида: "
        '{"optimized_title":"...","benefits":["..."],"description":"..."}. '
        f"Требования: optimized_title — SEO-заголовок до 180 символов; "
        f"benefits — список из 4-6 коротких ключевых преимуществ (буллеты) "
        f"для инфографики (без emoji); description — полный продающий SEO-текст "
        f"на русском с LSI-ключами и смысловыми тегами/фразами, не длиннее "
        f"{limit} символов. Не выдумывай сертификаты, гарантии и материалы, "
        f"которых нет во входных данных. "
        f"Заголовок: {fenced_title}. Категория: {fenced_category}. "
        f"Характеристики/фичи: {fenced_features}."
    )


def _parse_usage(raw: object) -> SeoTokenUsage:
    if not isinstance(raw, dict):
        return SeoTokenUsage()
    prompt = _safe_int(raw.get("prompt_tokens"))
    completion = _safe_int(raw.get("completion_tokens"))
    total = _safe_int(raw.get("total_tokens"))
    if total <= 0:
        total = prompt + completion
    return SeoTokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _safe_int(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _parse_seo_content(
    raw_text: str, *, request: SeoTextGenerateRequest
) -> SeoTextContent:
    raw = raw_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeoTextUpstreamError("OpenAI response is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise SeoTextUpstreamError("OpenAI JSON root must be an object.")

    # Accept alternate keys from the model.
    if "optimized_title" not in payload and isinstance(payload.get("title"), str):
        payload["optimized_title"] = payload["title"]
    if "benefits" not in payload and isinstance(payload.get("advantages"), list):
        payload["benefits"] = payload["advantages"]
    if "benefits" not in payload and isinstance(payload.get("characteristics"), list):
        payload["benefits"] = payload["characteristics"]

    try:
        content = SeoTextContent.model_validate(payload)
    except ValidationError as exc:
        raise SeoTextUpstreamError("OpenAI response failed SEO schema.") from exc

    max_chars = description_limit_for(request.target_platform)
    if len(content.description) > max_chars:
        truncated = content.description[:max_chars].rstrip()
        content = SeoTextContent(
            optimized_title=content.optimized_title,
            benefits=content.benefits,
            description=truncated,
        )
    return content


async def _record_openai_usage(
    *,
    model_name: str,
    usage: SeoTokenUsage,
    user_metadata: dict[str, Any] | None = None,
) -> None:
    total = usage.total_tokens
    if total <= 0:
        return
    total_cost = (
        Decimal(usage.prompt_tokens) / Decimal(1000) * _DEFAULT_INPUT_COST_PER_1K
        + Decimal(usage.completion_tokens) / Decimal(1000) * _DEFAULT_OUTPUT_COST_PER_1K
    )
    units = max(total, 1)
    metadata: dict[str, Any] = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    if user_metadata:
        metadata.update(user_metadata)
    await record_api_usage_cost(
        provider="openai",
        model_name=model_name,
        operation="seo_text_generation",
        units=units,
        unit_cost_usd=total_cost / Decimal(units),
        total_cost_usd=total_cost,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        status="Success",
        metadata=metadata,
    )
