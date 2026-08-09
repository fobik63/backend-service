"""LLM parser: natural-language canvas prompts → validated ``CanvasStateDTO``.

Translates free-form user instructions (colors, fonts, badges, layout) into a
strict Canvas JSON document that the server-side renderer can composite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx
from pydantic import ValidationError

from app.core.prompt_safety import fence_untrusted_text, harden_system_prompt
from app.schemas.templates import CanvasStateDTO
from app.services.infographic_service import (
    TRANSIENT_HTTP_CODES,
    LLMConfig,
    LLMIntegrationError,
)

logger = logging.getLogger(__name__)

PromptCompleter = Callable[[str, str], Awaitable[str]]

DEFAULT_CANVAS_WIDTH: Final[int] = 1080
DEFAULT_CANVAS_HEIGHT: Final[int] = 1440
_MAX_PROMPT_LENGTH: Final[int] = 8_000


class CanvasPromptParserError(Exception):
    """Base exception for canvas prompt parsing failures."""


class CanvasPromptParserConfigurationError(CanvasPromptParserError):
    """Raised when LLM settings are missing or invalid."""


class CanvasPromptParserValidationError(CanvasPromptParserError):
    """Raised when the user prompt or LLM JSON fails validation."""


class CanvasPromptParserUpstreamError(CanvasPromptParserError):
    """Raised when the LLM request/response cannot be trusted."""


_CANVAS_SCHEMA_HINT: Final[str] = """
Return ONLY a single JSON object matching CanvasStateDTO (no markdown fences):
{
  "width": 1080,
  "height": 1440,
  "background_color": "#FFFFFF",
  "background_image_url": null,
  "layers": [
    {
      "layer_type": "image|text|badge|shape",
      "id": "<uuid>",
      "name": "<non-empty string>",
      "visible": true,
      "locked": false,
      "x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0,
      "rotation": 0.0, "opacity": 1.0, "z_index": 0,
      // image: url, scale_x, scale_y, optional crop_*
      // text: text, font_family, font_size, font_weight, color_hex,
      //       alignment (left|center|right), line_height, letter_spacing,
      //       optional shadow_color, shadow_blur
      // badge: badge_type (discount|rating|top_sales), text, bg_color, text_color
      // shape: shape_type (rect|circle), fill_color, optional stroke_*
    }
  ]
}
Rules:
- Colors must be #RGB, #RRGGBB, or #RRGGBBAA hex.
- Prefer Inter / DejaVuSans for font_family when the user names a web font.
- Map Russian color words: синий→#2563EB, красный→#E11D48, белый→#FFFFFF,
  чёрный/черный→#111111, зелёный/зеленый→#16A34A.
- Price / sale stickers → badge layers (badge_type=discount unless specified).
- Product photo → image layer named "product" (or keep existing product layer id).
- "вправо" / "to the right" → increase product layer x toward the right side.
- Keep width/height at 1080×1440 unless the user asks otherwise.
- Preserve layer ids from the base canvas when editing; generate new UUIDs only
  for newly created layers.
- Output must be valid JSON only.
""".strip()


_SYSTEM_PROMPT: Final[str] = harden_system_prompt(
    "You are a senior marketplace card layout engineer for Wildberries and Ozon. "
    "Convert Russian or English natural-language edit instructions into a "
    "strict CanvasStateDTO JSON document for a 1080×1440 product card. "
    f"{_CANVAS_SCHEMA_HINT}"
)


class CanvasPromptParser:
    """Translate free-form text into a validated ``CanvasStateDTO`` via LLM."""

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        *,
        completer: PromptCompleter | None = None,
    ) -> None:
        """Create a parser.

        Prefer injecting ``completer`` in unit tests. When omitted, an HTTP
        OpenAI/Anthropic client is built from ``llm_config`` / env.
        """

        self._completer = completer
        self._llm_config: LLMConfig | None = None
        self._client: httpx.AsyncClient | None = None

        if completer is not None:
            return

        try:
            self._llm_config = llm_config or LLMConfig.from_env()
        except LLMIntegrationError as exc:
            raise CanvasPromptParserConfigurationError(str(exc)) from exc

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
        """Release HTTP resources when the default LLM client is used."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def parse(
        self,
        prompt: str,
        *,
        base_canvas: CanvasStateDTO | None = None,
    ) -> CanvasStateDTO:
        """Parse a natural-language instruction into ``CanvasStateDTO``.

        Parameters
        ----------
        prompt:
            User instruction, e.g. title color/font, price badge, product move.
        base_canvas:
            Optional existing canvas to edit. When ``None``, the model creates
            a fresh 1080×1440 document from the instruction alone.
        """

        cleaned = (prompt or "").strip()
        if not cleaned:
            raise CanvasPromptParserValidationError("Prompt must be a non-empty string.")
        if len(cleaned) > _MAX_PROMPT_LENGTH:
            raise CanvasPromptParserValidationError(
                f"Prompt exceeds {_MAX_PROMPT_LENGTH} characters."
            )

        system = _SYSTEM_PROMPT
        user = build_canvas_parser_user_prompt(cleaned, base_canvas)
        raw = await self._complete(system=system, user=user)
        return parse_canvas_json(raw)


    async def _complete(self, *, system: str, user: str) -> str:
        if self._completer is not None:
            return await self._completer(system, user)
        if self._llm_config is None or self._client is None:
            raise CanvasPromptParserConfigurationError("LLM client is not initialized.")
        if self._llm_config.provider == "openai":
            return await self._call_openai(system=system, user=user)
        return await self._call_anthropic(system=system, user=user)

    async def _call_openai(self, *, system: str, user: str) -> str:
        assert self._llm_config is not None
        headers = {
            "Authorization": f"Bearer {self._llm_config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._llm_config.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        response = await self._post_with_retry(
            endpoint="/v1/chat/completions",
            headers=headers,
            payload=payload,
        )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise CanvasPromptParserUpstreamError(
                "Unexpected OpenAI response shape."
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise CanvasPromptParserUpstreamError("OpenAI returned empty text.")
        return text

    async def _call_anthropic(self, *, system: str, user: str) -> str:
        assert self._llm_config is not None
        headers = {
            "x-api-key": self._llm_config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._llm_config.model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "system": system,
            "messages": [{"role": "user", "content": user}],
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
            raise CanvasPromptParserUpstreamError(
                "Unexpected Anthropic response shape."
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise CanvasPromptParserUpstreamError("Anthropic returned empty text.")
        return text

    async def _post_with_retry(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        assert self._client is not None
        assert self._llm_config is not None
        attempts = self._llm_config.max_retries + 1
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
                    raise CanvasPromptParserUpstreamError(
                        f"LLM API error {response.status_code}: {response.text[:500]}"
                    )
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._retry_delay(attempt, None))
        raise CanvasPromptParserUpstreamError(
            "LLM request failed after retries."
        ) from last_error

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        assert self._llm_config is not None
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
            self._llm_config.base_retry_delay_seconds * (2 ** (attempt - 1))
            + random.uniform(0.0, 0.35),
            10.0,
        )


def build_canvas_parser_user_prompt(
    prompt: str,
    base_canvas: CanvasStateDTO | None = None,
) -> str:
    """Assemble the user message with fenced instruction and optional base JSON."""

    fenced = fence_untrusted_text(
        prompt,
        label="canvas_edit_prompt",
        max_length=_MAX_PROMPT_LENGTH,
        reject_injection=False,
    )
    parts = [
        "Convert the following canvas edit instruction into a complete "
        "CanvasStateDTO JSON document.",
        fenced,
    ]
    if base_canvas is not None:
        parts.append(
            "Base canvas to edit (preserve layer ids where possible):\n"
            f"{base_canvas.model_dump_json()}"
        )
    else:
        parts.append(
            "No base canvas was provided. Create a fresh marketplace card "
            f"({DEFAULT_CANVAS_WIDTH}×{DEFAULT_CANVAS_HEIGHT}) that satisfies "
            "the instruction. Include at least a product image layer and any "
            "text/badge layers implied by the prompt."
        )
    parts.append("Respond with JSON only.")
    return "\n\n".join(parts)


def parse_canvas_json(raw_text: str) -> CanvasStateDTO:
    """Strip optional markdown fences and validate as ``CanvasStateDTO``."""

    raw = (raw_text or "").strip()
    if not raw:
        raise CanvasPromptParserUpstreamError("LLM returned empty canvas JSON.")

    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        # JSON path is required: CanvasStateDTO uses strict=True, so UUID / float
        # fields coerce from JSON strings/numbers but not from Python str via
        # model_validate (matches canvas renderer unit tests).
        canvas = CanvasStateDTO.model_validate_json(raw)
    except ValidationError as exc:
        # Distinguish malformed JSON from schema violations when possible.
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as json_exc:
            raise CanvasPromptParserUpstreamError(
                "LLM response is not valid JSON."
            ) from json_exc
        if not isinstance(payload, dict):
            raise CanvasPromptParserUpstreamError(
                "LLM response must be a JSON object."
            ) from exc
        raise CanvasPromptParserValidationError(
            "LLM response failed CanvasStateDTO schema validation."
        ) from exc

    return canvas


_default_parser: CanvasPromptParser | None = None


def get_canvas_prompt_parser() -> CanvasPromptParser:
    """Return a process-wide parser singleton (HTTP LLM backend)."""

    global _default_parser
    if _default_parser is None:
        _default_parser = CanvasPromptParser()
    return _default_parser


async def close_canvas_prompt_parser() -> None:
    """Close the singleton parser HTTP client if it was created."""

    global _default_parser
    if _default_parser is not None:
        await _default_parser.aclose()
        _default_parser = None
