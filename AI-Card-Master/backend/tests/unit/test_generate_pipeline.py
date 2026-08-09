"""Unit tests for POST /api/v1/generate-pipeline (n8n bridge)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.application.generate_pipeline_errors import (
    GeneratePipelineNotConfiguredError,
    GeneratePipelineTimeoutError,
    GeneratePipelineUpstreamError,
    GeneratePipelineValidationError,
)
from app.application.generate_pipeline_service import GeneratePipelineService
from app.core.config import Settings, get_settings
from app.infrastructure.n8n_pipeline_client import N8nPipelineClient
from app.schemas.generate_pipeline import (
    GeneratePipelineRequest,
    N8nPipelineResult,
)


def _settings(**overrides: object) -> Settings:
    get_settings.cache_clear()
    values: dict[str, object] = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/test",
        "JWT_SECRET_KEY": "unit-test-jwt-secret-key-with-enough-entropy-" + ("x" * 32),
        "N8N_WEBHOOK_URL": "https://n8n.test/webhook/generate-pipeline",
        "N8N_WEBHOOK_SECRET": "n8n-secret",
        "N8N_TIMEOUT_SECONDS": 30.0,
        "N8N_CONNECT_TIMEOUT_SECONDS": 5.0,
        "N8N_MAX_RETRIES": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_request_rejects_non_http_image_url() -> None:
    with pytest.raises(ValidationError):
        GeneratePipelineRequest(
            product_name="Sage Mist",
            image_url="ftp://files.example/product.png",
        )


def test_n8n_result_accepts_plaque_aliases() -> None:
    result = N8nPipelineResult.model_validate(
        {
            "layer_urls": {
                "background": "https://cdn.example/bg.png",
                "product": "https://cdn.example/product.png",
            },
            "plaques": [
                {
                    "text": "Эко",
                    "bg_color": "#2D6A4F",
                    "text_color": "#FFFFFF",
                }
            ],
        }
    )
    assert result.layers.background_url.endswith("/bg.png")
    assert result.badges[0].text == "Эко"
    assert result.badges[0].text_color == "#FFFFFF"


@pytest.mark.asyncio
@respx.mock
async def test_service_round_trip_returns_structured_response() -> None:
    settings = _settings()
    route = respx.post("https://n8n.test/webhook/generate-pipeline").mock(
        return_value=httpx.Response(
            200,
            json={
                "layers": {
                    "background_url": "https://cdn.example/bg.png",
                    "product_url": "https://cdn.example/cutout.png",
                },
                "badges": [
                    {
                        "text": "Хит продаж",
                        "bg_color": "#F59E0B",
                        "text_color": "#111827",
                        "icon_id": "flame",
                        "x": 10.0,
                        "y": 12.0,
                    }
                ],
            },
        )
    )

    service = GeneratePipelineService(N8nPipelineClient(settings))
    body = GeneratePipelineRequest(
        product_name="Sage Mist",
        product_category="creams",
        image_url="https://cdn.example/source.png",
        marketplace="wildberries",
        benefits=["Эко-формула", "24ч увлажнение"],
    )
    request_id = uuid4()
    user_id = uuid4()

    response = await service.run(user_id=user_id, body=body, request_id=request_id)

    assert route.called
    sent = route.calls[0].request
    assert sent.headers.get("x-n8n-webhook-secret") == "n8n-secret"
    assert response.success is True
    assert response.request_id == request_id
    assert response.product_name == "Sage Mist"
    assert response.layers.product_url == "https://cdn.example/cutout.png"
    assert len(response.badges) == 1
    assert response.badges[0].text == "Хит продаж"


@pytest.mark.asyncio
@respx.mock
async def test_service_maps_invalid_n8n_payload() -> None:
    settings = _settings()
    respx.post("https://n8n.test/webhook/generate-pipeline").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    service = GeneratePipelineService(N8nPipelineClient(settings))
    body = GeneratePipelineRequest(
        product_name="Sage Mist",
        image_url="https://cdn.example/source.png",
    )

    with pytest.raises(GeneratePipelineValidationError):
        await service.run(user_id=uuid4(), body=body, request_id=uuid4())


@pytest.mark.asyncio
async def test_client_requires_webhook_url() -> None:
    settings = _settings(N8N_WEBHOOK_URL="")
    client = N8nPipelineClient(settings)
    with pytest.raises(GeneratePipelineNotConfiguredError):
        await client.invoke({"product_name": "x"})


@pytest.mark.asyncio
@respx.mock
async def test_client_maps_timeout() -> None:
    settings = _settings()
    respx.post("https://n8n.test/webhook/generate-pipeline").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    client = N8nPipelineClient(settings)
    with pytest.raises(GeneratePipelineTimeoutError):
        await client.invoke({"product_name": "x"})


@pytest.mark.asyncio
@respx.mock
async def test_client_maps_upstream_http_error() -> None:
    settings = _settings()
    respx.post("https://n8n.test/webhook/generate-pipeline").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    client = N8nPipelineClient(settings)
    with pytest.raises(GeneratePipelineUpstreamError):
        await client.invoke({"product_name": "x"})


def test_openapi_exposes_generate_pipeline() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/generate-pipeline" in paths
    assert "post" in paths["/api/v1/generate-pipeline"]
