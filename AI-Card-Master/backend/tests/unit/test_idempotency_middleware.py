"""Unit tests for Redis idempotency middleware (coin / generation mutations)."""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.idempotency_middleware import IdempotencyMiddleware, _is_protected_path
from app.infrastructure import redis as redis_module


def _settings(**overrides: Any) -> Settings:
    data: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "j" * 64,
        "APP_ENV": "development",
        "IDEMPOTENCY_MIDDLEWARE_ENABLED": True,
        "IDEMPOTENCY_PROCESSING_TTL_SECONDS": 60,
        "IDEMPOTENCY_RESPONSE_TTL_SECONDS": 900,
    }
    data.update(overrides)
    return Settings(**data)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeAsyncRedis:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    monkeypatch.setattr(redis_module, "get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def idempotent_app(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.FakeAsyncRedis,
) -> tuple[FastAPI, list[int]]:
    _ = fake_redis
    settings = _settings()
    monkeypatch.setattr(
        "app.core.idempotency_middleware.get_settings",
        lambda: settings,
    )

    hits: list[int] = []
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/generations")
    async def create_generation() -> dict[str, object]:
        hits.append(1)
        return {"task_id": "abc", "status": "queued"}

    @app.post("/api/v1/generations/slow")
    async def slow_generation() -> dict[str, object]:
        hits.append(1)
        await asyncio.sleep(0.15)
        return {"task_id": "slow", "status": "queued"}

    @app.post("/api/v1/generations/error")
    async def error_generation(request: Request) -> dict[str, object]:
        _ = request
        hits.append(1)
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient AI-coin balance.",
        )

    @app.get("/api/v1/generations/history")
    async def history() -> dict[str, bool]:
        hits.append(1)
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        hits.append(1)
        return {"ok": True}

    return app, hits


def test_protected_path_matching() -> None:
    assert _is_protected_path("/api/v1/generations")
    assert _is_protected_path("/api/v1/generations/model")
    assert _is_protected_path("/api/v1/bulk-generations")
    assert _is_protected_path("/api/v1/payments/create")
    assert not _is_protected_path("/api/v1/payments/balance")
    assert not _is_protected_path("/api/v1/auth/login")
    assert not _is_protected_path("/health")


def test_without_header_passes_through(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    first = client.post("/api/v1/generations")
    second = client.post("/api/v1/generations")
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(hits) == 2


def test_first_request_claims_and_caches_response(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    headers = {"X-Idempotency-Key": "client-key-001"}
    first = client.post("/api/v1/generations", headers=headers)
    second = client.post("/api/v1/generations", headers=headers)

    assert first.status_code == 200
    assert first.json() == {"task_id": "abc", "status": "queued"}
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers.get("X-Idempotency-Replayed") == "true"
    assert len(hits) == 1


def test_legacy_idempotency_key_header_supported(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    headers = {"Idempotency-Key": "legacy-key-01"}
    first = client.post("/api/v1/generations", headers=headers)
    second = client.post("/api/v1/generations", headers=headers)
    assert first.status_code == 200
    assert second.headers.get("X-Idempotency-Replayed") == "true"
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_concurrent_processing_returns_409(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    headers = {"X-Idempotency-Key": "inflight-key-1"}

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        first_task = asyncio.create_task(
            async_client.post("/api/v1/generations/slow", headers=headers)
        )
        await asyncio.sleep(0.05)
        second = await async_client.post("/api/v1/generations/slow", headers=headers)
        first = await first_task

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Запрос уже обрабатывается"
    assert len(hits) == 1


def test_error_releases_processing_so_retry_works(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    headers = {"X-Idempotency-Key": "retry-after-fail"}

    first = client.post("/api/v1/generations/error", headers=headers)
    second = client.post("/api/v1/generations/error", headers=headers)

    assert first.status_code == 402
    assert second.status_code == 402
    assert second.headers.get("X-Idempotency-Replayed") is None
    assert len(hits) == 2


def test_invalid_key_rejected(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, _hits = idempotent_app
    client = TestClient(app)
    response = client.post(
        "/api/v1/generations",
        headers={"X-Idempotency-Key": "short"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_unprotected_route_ignores_header(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    headers = {"X-Idempotency-Key": "auth-key-001"}
    assert client.post("/api/v1/auth/login", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/login", headers=headers).status_code == 200
    assert len(hits) == 2


def test_get_is_not_idempotent_gated(
    idempotent_app: tuple[FastAPI, list[int]],
) -> None:
    app, hits = idempotent_app
    client = TestClient(app)
    headers = {"X-Idempotency-Key": "get-key-0001"}
    assert client.get("/api/v1/generations/history", headers=headers).status_code == 200
    assert client.get("/api/v1/generations/history", headers=headers).status_code == 200
    assert len(hits) == 2
