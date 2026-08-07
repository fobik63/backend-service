"""Unit tests for Smart Reasoning Routing & analytics caching (plan §55)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.smart_reasoning_router import SmartReasoningRouter
from app.core.config import Settings
from app.domain.smart_reasoning import (
    ReasoningTaskKind,
    ReasoningTier,
    analytics_fingerprint,
    fingerprint_messages_request,
    model_for_task,
    model_supports_adaptive_thinking,
    redis_analytics_key,
    tier_for_task,
)
from app.infrastructure.claude.client import Claude47VisionClient


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "t" * 64,
        "CLAUDE_47_API_KEY": "claude-test-key",
        "CLAUDE_47_MODEL": "claude-opus-4-7",
        "CLAUDE_35_HAIKU_MODEL": "claude-3-5-haiku-20241022",
        "CLAUDE_ANALYTICS_CACHE_TTL_SECONDS": 86400,
    }
    base.update(overrides)
    return Settings(**base)


def test_eye_of_god_routes_to_opus() -> None:
    assert tier_for_task(ReasoningTaskKind.EYE_OF_GOD) is ReasoningTier.DEEP
    assert (
        model_for_task(
            ReasoningTaskKind.EYE_OF_GOD,
            simple_model="claude-3-5-haiku-20241022",
            deep_model="claude-opus-4-7",
        )
        == "claude-opus-4-7"
    )


def test_simple_tasks_route_to_haiku() -> None:
    simple = (
        ReasoningTaskKind.PAIN_ANALYSIS,
        ReasoningTaskKind.ORACLE_ENRICHMENT,
        ReasoningTaskKind.AB_HYPOTHESES,
        ReasoningTaskKind.AI_STRATEGY,
    )
    for kind in simple:
        assert tier_for_task(kind) is ReasoningTier.SIMPLE
        assert (
            model_for_task(
                kind,
                simple_model="claude-3-5-haiku-20241022",
                deep_model="claude-opus-4-7",
            )
            == "claude-3-5-haiku-20241022"
        )


def test_deep_vision_tasks_stay_on_opus() -> None:
    deep = (
        ReasoningTaskKind.VISUAL_AUDIT,
        ReasoningTaskKind.COMPETITOR_AUDIT,
        ReasoningTaskKind.CLAUDE_REASONING,
        ReasoningTaskKind.EYE_OF_GOD,
    )
    for kind in deep:
        assert tier_for_task(kind) is ReasoningTier.DEEP
        assert tier_for_task(kind, has_vision=True) is ReasoningTier.DEEP


def test_text_only_vision_tasks_downgrade_to_haiku() -> None:
    for kind in (
        ReasoningTaskKind.COMPETITOR_AUDIT,
        ReasoningTaskKind.CLAUDE_REASONING,
        ReasoningTaskKind.EYE_OF_GOD,
        ReasoningTaskKind.VISUAL_AUDIT,
    ):
        assert tier_for_task(kind, has_vision=False) is ReasoningTier.SIMPLE
        assert (
            model_for_task(
                kind,
                simple_model="claude-3-5-haiku-20241022",
                deep_model="claude-opus-4-7",
                has_vision=False,
            )
            == "claude-3-5-haiku-20241022"
        )


def test_zero_hallucination_and_export_use_simple_tier() -> None:
    for kind in (
        ReasoningTaskKind.ZERO_HALLUCINATION,
        ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX,
    ):
        assert tier_for_task(kind) is ReasoningTier.SIMPLE
        assert (
            model_for_task(
                kind,
                simple_model="claude-3-5-haiku-20241022",
                deep_model="claude-opus-4-7",
            )
            == "claude-3-5-haiku-20241022"
        )

def test_router_matches_settings_models() -> None:
    router = SmartReasoningRouter(
        simple_model="claude-3-5-haiku-20241022",
        deep_model="claude-opus-4-7",
    )
    assert router.model_for(ReasoningTaskKind.PAIN_ANALYSIS).endswith("haiku-20241022")
    assert router.model_for(ReasoningTaskKind.EYE_OF_GOD) == "claude-opus-4-7"


def test_adaptive_thinking_detection() -> None:
    assert model_supports_adaptive_thinking("claude-opus-4-7") is True
    assert model_supports_adaptive_thinking("claude-3-5-haiku-20241022") is False
    assert model_supports_adaptive_thinking("claude-3-5-sonnet-20241022") is False


def test_analytics_cache_key_stable() -> None:
    fp = analytics_fingerprint({"a": 1, "b": [2, 3]})
    key = redis_analytics_key(
        task_kind="pain_analysis",
        model_name="claude-3-5-haiku-20241022",
        fingerprint=fp,
    )
    assert key.startswith("claude:analytics:v1:pain_analysis:")
    assert fp in key
    assert analytics_fingerprint({"b": [2, 3], "a": 1}) == fp


def test_fingerprint_hashes_image_payloads() -> None:
    fp1 = fingerprint_messages_request(
        model_name="claude-opus-4-7",
        system="sys",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "AAAA",
                },
            }
        ],
        json_schema={"type": "object"},
        operation="eye",
    )
    fp2 = fingerprint_messages_request(
        model_name="claude-opus-4-7",
        system="sys",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "BBBB",
                },
            }
        ],
        json_schema={"type": "object"},
        operation="eye",
    )
    assert fp1 != fp2
    assert len(fp1) == 64


@pytest.mark.asyncio
async def test_messages_json_cache_hit_skips_upstream() -> None:
    settings = _settings()
    cache = MagicMock()
    cache.get = AsyncMock(
        return_value={"payload": {"ok": True, "score": 1}, "cache_hit": True}
    )
    cache.set = AsyncMock()

    client = Claude47VisionClient(
        settings,
        model_name="claude-3-5-haiku-20241022",
        analytics_cache=cache,
        analytics_cache_ttl_seconds=86400,
        analytics_task_kind="pain_analysis",
    )
    client._messages_create_with_retry = AsyncMock()  # type: ignore[method-assign]
    client._record_usage = AsyncMock()  # type: ignore[method-assign]

    try:
        assert client.uses_adaptive_thinking is False
        parsed, in_tok, out_tok = await client._messages_json(
            system="sys",
            content=[{"type": "text", "text": "hello"}],
            json_schema={"type": "object"},
            max_tokens=100,
            operation="claude_pain_analysis",
            user_id=None,
            job_id=None,
        )
        assert parsed == {"ok": True, "score": 1}
        assert in_tok == 0
        assert out_tok == 0
        client._messages_create_with_retry.assert_not_awaited()
        cache.set.assert_not_awaited()
    finally:
        with patch.object(client._sdk, "close", new=AsyncMock()):
            await client.aclose()


@pytest.mark.asyncio
async def test_haiku_payload_omits_adaptive_thinking() -> None:
    settings = _settings()
    captured: dict[str, Any] = {}

    async def _capture(
        *,
        create_kwargs: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
        sdk: Any = None,
        track_primary: bool = True,
    ):
        captured["payload"] = create_kwargs
        captured["extra_headers"] = extra_headers
        response = MagicMock()
        response.content = [MagicMock(type="text", text='{"result":"ok"}')]
        response.usage = MagicMock(input_tokens=3, output_tokens=2)
        return response

    client = Claude47VisionClient(
        settings,
        model_name="claude-3-5-haiku-20241022",
        analytics_cache=None,
    )
    client._messages_create_with_retry = _capture  # type: ignore[method-assign]
    client._record_usage = AsyncMock()  # type: ignore[method-assign]

    try:
        parsed, in_tok, out_tok = await client._messages_json(
            system="sys",
            content=[{"type": "text", "text": "hello"}],
            json_schema={"type": "object", "properties": {}},
            max_tokens=50,
            operation="unit_haiku",
            user_id=None,
            job_id=None,
        )
        assert parsed == {"result": "ok"}
        assert in_tok == 3
        assert out_tok == 2
        body = captured["payload"]
        assert body["model"] == "claude-3-5-haiku-20241022"
        assert "thinking" not in body
        assert "output_config" not in body
        assert "temperature" in body
        system = body["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert "Respond with a single JSON object" in system[0]["text"]
    finally:
        with patch.object(client._sdk, "close", new=AsyncMock()):
            await client.aclose()


@pytest.mark.asyncio
async def test_opus_payload_keeps_adaptive_thinking() -> None:
    settings = _settings()
    captured: dict[str, Any] = {}

    async def _capture(
        *,
        create_kwargs: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
        sdk: Any = None,
        track_primary: bool = True,
    ):
        captured["payload"] = create_kwargs
        captured["extra_headers"] = extra_headers
        response = MagicMock()
        response.content = [MagicMock(type="text", text='{"result":"deep"}')]
        response.usage = MagicMock(input_tokens=11, output_tokens=7)
        return response

    client = Claude47VisionClient(
        settings,
        model_name="claude-opus-4-7",
        analytics_cache=None,
    )
    client._messages_create_with_retry = _capture  # type: ignore[method-assign]
    client._record_usage = AsyncMock()  # type: ignore[method-assign]

    try:
        assert client.uses_adaptive_thinking is True
        await client._messages_json(
            system="sys",
            content=[{"type": "text", "text": "deep"}],
            json_schema={"type": "object"},
            max_tokens=50,
            operation="unit_opus",
            user_id=None,
            job_id=None,
        )
        body = captured["payload"]
        assert body["thinking"] == {"type": "adaptive"}
        assert "output_config" in body
        assert "temperature" not in body
        system = body["system"]
        assert isinstance(system, list)
        assert system[0]["type"] == "text"
        assert system[0]["cache_control"] == {"type": "ephemeral"}
    finally:
        with patch.object(client._sdk, "close", new=AsyncMock()):
            await client.aclose()


def test_default_analytics_ttl_is_24h() -> None:
    settings = _settings()
    assert settings.claude_analytics_cache_ttl_seconds == 86400
    assert settings.claude_47_stage_cache_ttl_seconds == 86400
