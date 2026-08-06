"""AI service for marketplace-ready product copy from generated images."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from decimal import Decimal
from typing import Any

import httpx
from pydantic import ValidationError

from app.domain.generation import MarketplaceTextContent, SlideWorkItem
from app.core.config import get_settings
from app.core.prompt_safety import fence_untrusted_text, harden_system_prompt
from app.services.api_usage_costs import record_api_usage_cost
from app.services.ai_engine import _detect_image_mime_type
from app.services.infographic_service import (
    LLMConfig,
    LLMIntegrationError,
    TRANSIENT_HTTP_CODES,
)

logger = logging.getLogger(__name__)


class MarketplaceTextServiceError(Exception):
    """Base exception for marketplace text generation failures."""


class MarketplaceTextConfigurationError(MarketplaceTextServiceError):
    """Raised when LLM settings are missing or invalid."""


class MarketplaceTextUpstreamError(MarketplaceTextServiceError):
    """Raised when the LLM request or response cannot be trusted."""


class MarketplaceTextService:
    """Generate WB/Ozon copy after the visual card series is complete."""

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        try:
            self._llm_config = llm_config or LLMConfig.from_env()
        except LLMIntegrationError as exc:
            raise MarketplaceTextConfigurationError(str(exc)) from exc
        self._client = httpx.AsyncClient(
            base_url=self._llm_config.base_url.rstrip("/"),
            timeout=httpx.Timeout(self._llm_config.timeout_seconds),
            limits=httpx.Limits(
                max_connections=self._llm_config.max_connections,
                max_keepalive_connections=self._llm_config.max_keepalive_connections,
                keepalive_expiry=30.0,
            ),
            http2=True,
        )

    async def aclose(self) -> None:
        """Release HTTP resources."""

        await self._client.aclose()

    async def generate_marketplace_text(
        self,
        *,
        product_category: str | None,
        slides: tuple[SlideWorkItem, ...],
        images: tuple[bytes, ...],
    ) -> MarketplaceTextContent:
        """Analyze final generated cards and return strict marketplace JSON."""

        if not images:
            raise MarketplaceTextUpstreamError("No generated images were provided.")
        if len(slides) != len(images):
            raise MarketplaceTextUpstreamError("Slides and image payloads do not match.")

        if self._llm_config.provider == "openai":
            raw_text = await self._call_openai(product_category, slides, images)
        else:
            raw_text = await self._call_anthropic(product_category, slides, images)
        return _parse_marketplace_text(raw_text)

    async def _call_openai(
        self,
        product_category: str | None,
        slides: tuple[SlideWorkItem, ...],
        images: tuple[bytes, ...],
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._llm_config.api_key}",
            "Content-Type": "application/json",
        }
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _build_user_prompt(product_category, slides),
            }
        ]
        for image in images[:5]:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_uri(image)},
                }
            )
        payload: dict[str, Any] = {
            "model": self._llm_config.model,
            "temperature": 0.45,
            "max_tokens": 1700,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        response = await self._post_with_retry(
            endpoint="/v1/chat/completions",
            headers=headers,
            payload=payload,
        )
        try:
            payload_json = response.json()
            content = payload_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MarketplaceTextUpstreamError("Unexpected OpenAI response shape.") from exc
        if not isinstance(content, str) or not content.strip():
            raise MarketplaceTextUpstreamError("OpenAI returned empty text.")
        return content

    async def _call_anthropic(
        self,
        product_category: str | None,
        slides: tuple[SlideWorkItem, ...],
        images: tuple[bytes, ...],
    ) -> str:
        headers = {
            "x-api-key": self._llm_config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _build_user_prompt(product_category, slides),
            }
        ]
        for image in images[:5]:
            mime_type, _extension = _detect_image_mime_type(image)
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        payload: dict[str, Any] = {
            "model": self._llm_config.model,
            "max_tokens": 1700,
            "temperature": 0.45,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
        }
        response = await self._post_with_retry(
            endpoint="/v1/messages",
            headers=headers,
            payload=payload,
        )
        try:
            payload_json = response.json()
            response_content = payload_json["content"]
            text = response_content[0]["text"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MarketplaceTextUpstreamError("Unexpected Anthropic response shape.") from exc
        if not isinstance(text, str) or not text.strip():
            raise MarketplaceTextUpstreamError("Anthropic returned empty text.")
        await _record_anthropic_usage_cost(
            model_name=self._llm_config.model,
            response_payload=payload_json,
        )
        return text

    async def _post_with_retry(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        attempts = self._llm_config.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(endpoint, headers=headers, json=payload)
                if response.status_code in TRANSIENT_HTTP_CODES and attempt < attempts:
                    await asyncio.sleep(self._retry_delay(attempt, response))
                    continue
                if response.is_error:
                    raise MarketplaceTextUpstreamError(
                        f"LLM API error {response.status_code}: {response.text[:500]}"
                    )
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._retry_delay(attempt, None))
        raise MarketplaceTextUpstreamError("LLM request failed after retries.") from last_error

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after)
                    if parsed > 0:
                        return min(parsed, 10.0)
                except ValueError:
                    logger.debug("Ignoring non-numeric Retry-After value: %s", retry_after)
        return min(
            self._llm_config.base_retry_delay_seconds * (2 ** (attempt - 1))
            + random.uniform(0.0, 0.35),
            10.0,
        )



_SYSTEM_PROMPT = harden_system_prompt(
    "You are a senior Russian marketplace SEO copywriter for Wildberries and Ozon. "
    "Analyze product card images and produce factual, conversion-focused copy. "
    "Return only valid JSON without markdown."
)


def _build_user_prompt(
    product_category: str | None,
    slides: tuple[SlideWorkItem, ...],
) -> str:
    slide_context = "; ".join(
        f"{slide.position}. {slide.slide_key}: {slide.prompt}" for slide in slides
    )
    category = product_category.strip() if product_category else "не указана"
    fenced_category = fence_untrusted_text(category, label="product_category")
    fenced_slides = fence_untrusted_text(slide_context, label="slide_context")
    return (
        "Проанализируй сгенерированные изображения товара и подготовь JSON для карточки "
        "WB/Ozon. Структура строго такая: "
        '{"title": "...", "description": "...", "characteristics": ["...", "..."]}. '
        "Требования: title - SEO-заголовок до 180 символов, оптимизированный под "
        "поисковые алгоритмы Wildberries/Ozon; description - продающий текст на русском "
        "языке минимум 1000 символов с LSI-ключами, без выдуманных фактов, сертификатов, "
        "гарантий и точных материалов, если их не видно; characteristics - 3-12 коротких "
        "ключевых преимуществ товара. Не используй emoji, markdown и HTML. "
        f"Категория товара: {fenced_category}. Контекст слайдов: {fenced_slides}."
    )


def _image_data_uri(image: bytes) -> str:
    mime_type, _extension = _detect_image_mime_type(image)
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _record_anthropic_usage_cost(
    *,
    model_name: str,
    response_payload: dict[str, Any],
) -> None:
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return

    input_tokens = _safe_token_count(usage.get("input_tokens"))
    output_tokens = _safe_token_count(usage.get("output_tokens"))
    total_tokens = input_tokens + output_tokens
    settings = get_settings()
    total_cost = (
        Decimal(input_tokens)
        / Decimal(1000)
        * settings.claude_47_input_1k_tokens_cost_usd
        + Decimal(output_tokens)
        / Decimal(1000)
        * settings.claude_47_output_1k_tokens_cost_usd
    )
    units = max(total_tokens, 1)
    await record_api_usage_cost(
        provider="anthropic",
        model_name=model_name,
        operation="marketplace_text_generation",
        units=units,
        unit_cost_usd=total_cost / Decimal(units),
        total_cost_usd=total_cost,
        metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "anthropic_usage": usage,
        },
    )


def _safe_token_count(value: object) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _parse_marketplace_text(raw_text: str) -> MarketplaceTextContent:
    raw = raw_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MarketplaceTextUpstreamError("LLM response is not valid JSON.") from exc
    try:
        return MarketplaceTextContent.model_validate(payload)
    except ValidationError as exc:
        raise MarketplaceTextUpstreamError("LLM response failed marketplace schema.") from exc


_marketplace_text_service: MarketplaceTextService | None = None


def get_marketplace_text_service() -> MarketplaceTextService:
    """Return singleton LLM provider for marketplace copy generation."""

    global _marketplace_text_service
    if _marketplace_text_service is None:
        _marketplace_text_service = MarketplaceTextService()
    return _marketplace_text_service


async def close_marketplace_text_service() -> None:
    """Close singleton service resources."""

    global _marketplace_text_service
    if _marketplace_text_service is not None:
        await _marketplace_text_service.aclose()
        _marketplace_text_service = None
