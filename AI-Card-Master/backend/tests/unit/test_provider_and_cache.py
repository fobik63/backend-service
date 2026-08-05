from __future__ import annotations

import hashlib
import hmac
import io
import json

import fakeredis
import pytest
import respx
from httpx import Response
from PIL import Image

import app.infrastructure.redis as redis_module
import app.infrastructure.style_cache as style_cache_module
from app.config.style_presets import get_niche_preset_cached
from app.infrastructure.redis import (
    is_provider_circuit_open,
    record_provider_failure,
)
from app.services.ai_engine import (
    AIEngineValidationError,
    MidjourneyConfig,
    MidjourneyService,
)


def _product_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 40, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
@respx.mock
async def test_midjourney_submit_returns_without_polling() -> None:
    route = respx.post("https://provider.test/jobs/imagine").mock(
        return_value=Response(201, json={"jobid": "job-123", "status": "created"})
    )
    service = MidjourneyService(
        MidjourneyConfig(
            api_key="provider-key",
            base_url="https://provider.test",
            name="primary",
            webhook_token="webhook-secret",
            max_retries=0,
        )
    )
    try:
        submission = await service.submit(
            product_image=_product_png(),
            selected_style="studio",
            prompt="clean premium background",
            reply_url="https://api.test/webhook?token=secret",
            reply_ref="signed.reply.reference",
        )
    finally:
        await service.aclose()

    assert submission.external_job_id == "job-123"
    assert submission.provider == "primary"
    assert route.call_count == 1
    request_json = json.loads(route.calls[0].request.content)
    assert request_json["replyUrl"] == "https://api.test/webhook?token=secret"
    assert request_json["replyRef"] == "signed.reply.reference"
    assert request_json["stream"] is False


@pytest.mark.asyncio
async def test_webhook_auth_and_normalization() -> None:
    service = MidjourneyService(
        MidjourneyConfig(
            api_key="provider-key",
            base_url="https://provider.test",
            name="primary",
            webhook_token="webhook-secret",
        )
    )
    payload = {
        "eventId": "delivery-1",
        "jobid": "job-123",
        "status": "COMPLETED",
        "progress": "100%",
        "replyRef": "signed.reply.reference",
        "attachments": [{"url": "https://cdn.provider.test/result.png"}],
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(b"webhook-secret", raw, hashlib.sha256).hexdigest()

    assert service.verify_webhook(
        headers={"x-webhook-signature": f"sha256={signature}"},
        raw_body=raw,
        callback_token=None,
    )
    assert service.verify_webhook(
        headers={},
        raw_body=raw,
        callback_token="webhook-secret",
    )
    event = service.parse_webhook(payload)
    progress_event = service.parse_webhook({**payload, "progress": "50%"})
    duplicate = service.parse_webhook(payload)
    assert event.status == "completed"
    assert event.progress == 100
    assert event.external_job_id == "job-123"
    assert str(event.result_url) == "https://cdn.provider.test/result.png"
    assert event.event_id == duplicate.event_id
    assert event.event_id != progress_event.event_id
    await service.aclose()


@pytest.mark.asyncio
async def test_result_download_rejects_non_https_url_before_network() -> None:
    service = MidjourneyService(
        MidjourneyConfig(
            api_key="provider-key",
            base_url="https://provider.test",
            name="primary",
            webhook_token="webhook-secret",
        )
    )
    try:
        with pytest.raises(AIEngineValidationError):
            await service.download_result("http://127.0.0.1/internal.png")
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_redis_circuit_breaker_opens_after_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)

    assert not await is_provider_circuit_open("primary")
    await record_provider_failure("primary")
    await record_provider_failure("primary")
    await record_provider_failure("primary")

    assert await is_provider_circuit_open("primary")
    await fake.aclose()


@pytest.mark.asyncio
async def test_style_cache_populates_redis_and_counts_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)

    first = await get_niche_preset_cached("perfume")
    second = await get_niche_preset_cached("духи")

    assert first == second
    assert first is not None
    assert first["title"] == "Парфюмерия"
    assert len(await fake.keys("style:preset:*:perfume")) == 1
    assert int(await fake.get("style:usage:perfume")) == 2
    await fake.aclose()


@pytest.mark.asyncio
async def test_style_cache_falls_back_to_local_json_when_redis_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def redis_down(*args: object, **kwargs: object) -> dict[str, object] | None:
        raise style_cache_module.RedisUnavailableError("redis unavailable")

    monkeypatch.setattr(style_cache_module, "get_cached_json", redis_down)
    monkeypatch.setattr(style_cache_module, "cache_json", redis_down)

    preset = await style_cache_module.RedisStylePresetCache().get_niche("electronics")

    assert preset is not None
    assert preset["title"] == "Электроника"
