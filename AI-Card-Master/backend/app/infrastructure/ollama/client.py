"""Ollama (Llama 3) adapter for routine text workloads (plan §69)."""

from __future__ import annotations

import json
import logging
import re
import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from app.domain.pain_analysis import (
    PainAnalysisRequest,
    PainAnalysisResult,
    build_pain_analysis_prompt,
    normalize_claude_pain_result,
    pain_analysis_system_prompt,
)
from app.domain.semantic_filter import estimate_text_tokens
from app.services.api_usage_costs import record_api_usage_cost

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Local LLM call failure."""


class OllamaClient:
    """Thin async client for Ollama's ``/api/chat`` JSON mode."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 60.0,
        enabled: bool = True,
    ) -> None:
        base = base_url.strip().rstrip("/")
        model = model_name.strip()
        if not base:
            raise ValueError("base_url must not be empty.")
        if not model:
            raise ValueError("model_name must not be empty.")
        self._base_url = base
        self._model = model
        self._enabled = enabled
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=self._timeout,
            headers={"Content-Type": "application/json"},
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        return self._enabled

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        """Chat completion expecting a JSON object in the assistant message."""

        if not self._enabled:
            raise OllamaError("Ollama client is disabled.")

        user_payload = user
        if schema_hint:
            user_payload = f"{user}\n\nRespond with STRICT JSON matching:\n{schema_hint}"

        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_payload},
            ],
            "options": {"temperature": 0.1},
        }
        started = time.perf_counter()
        try:
            response = await self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            await self._record_usage(
                operation="ollama_complete_json",
                input_tokens=estimate_text_tokens(system + user_payload),
                output_tokens=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="Timeout",
            )
            raise OllamaError(f"Ollama timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            await self._record_usage(
                operation="ollama_complete_json",
                input_tokens=estimate_text_tokens(system + user_payload),
                output_tokens=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="Error",
            )
            raise OllamaError(f"Ollama HTTP error: {exc}") from exc
        except ValueError as exc:
            await self._record_usage(
                operation="ollama_complete_json",
                input_tokens=0,
                output_tokens=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="Error",
            )
            raise OllamaError(f"Ollama returned non-JSON: {exc}") from exc

        content = ""
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, dict):
            content = str(message.get("content") or "")
        if not content.strip():
            await self._record_usage(
                operation="ollama_complete_json",
                input_tokens=0,
                output_tokens=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="Error",
            )
            raise OllamaError("Ollama returned empty message content.")

        parsed = _parse_json_object(content)
        prompt_est = int(payload.get("prompt_eval_count") or 0) if isinstance(payload, dict) else 0
        eval_est = int(payload.get("eval_count") or 0) if isinstance(payload, dict) else 0
        in_tok = prompt_est or estimate_text_tokens(system + user_payload)
        out_tok = eval_est or estimate_text_tokens(content)
        await self._record_usage(
            operation="ollama_complete_json",
            input_tokens=in_tok,
            output_tokens=out_tok,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="Success",
        )
        return parsed, in_tok, out_tok

    async def _record_usage(
        self,
        *,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int | None,
        status: str,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> None:
        """Local LLM calls are free but still tracked for resource analytics."""

        await record_api_usage_cost(
            provider="ollama",
            model_name=self._model,
            operation=operation,
            units=max(input_tokens + output_tokens, 1),
            unit_cost_usd=Decimal("0"),
            total_cost_usd=Decimal("0"),
            user_id=user_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            duration_ms=duration_ms,
            task_id=job_id,
            metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "local": True,
            },
        )

    async def analyze_competitor_pains(
        self,
        *,
        request: PainAnalysisRequest,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[PainAnalysisResult, int, int]:
        """Run pain analysis on local Llama — same prompt contract as Claude Haiku."""

        _ = user_id, job_id
        payload_json, in_tok, out_tok = await self.complete_json(
            system=pain_analysis_system_prompt(),
            user=build_pain_analysis_prompt(request=request),
            schema_hint=(
                '{"filtered_out_junk":[],"real_product_pains":[],'
                '"infographic_badges":["","","",""],'
                '"seo_title":"","seo_description":""}'
            ),
        )
        try:
            result = normalize_claude_pain_result(
                payload_json,
                model_name=f"ollama:{self._model}",
            )
        except (ValueError, Exception) as exc:
            raise OllamaError(f"Ollama pain analysis failed validation: {exc}") from exc
        return result, in_tok, out_tok

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise OllamaError("Ollama response is not a JSON object.")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise OllamaError("Ollama JSON root must be an object.")
    return parsed
