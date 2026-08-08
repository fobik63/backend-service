"""Unit tests for isolated /healthz and /readyz infrastructure probes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.health.probes import ReadinessReport, check_deep_health, check_readiness
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz_returns_minimal_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_check_readiness_reports_first_failed_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.health.probes.postgres_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.redis_healthcheck",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.celery_workers_healthcheck",
        AsyncMock(return_value=True),
    )

    report = await check_readiness()

    assert report.healthy is False
    assert report.failed_service == "redis"
    assert report.checks == {"postgres": True, "redis": False, "celery": True}


@pytest.mark.asyncio
async def test_check_readiness_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.infrastructure.health.probes.postgres_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.redis_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.celery_workers_healthcheck",
        AsyncMock(return_value=True),
    )

    report = await check_readiness()

    assert report == ReadinessReport(
        healthy=True,
        failed_service=None,
        checks={"postgres": True, "redis": True, "celery": True},
    )


@pytest.mark.asyncio
async def test_check_deep_health_includes_s3_and_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.health.probes.postgres_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.redis_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.s3_healthcheck",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.ffmpeg_healthcheck",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.infrastructure.health.probes.celery_workers_healthcheck",
        AsyncMock(return_value=True),
    )

    report = await check_deep_health()

    assert report.healthy is False
    assert report.failed_service == "ffmpeg"
    assert report.checks["s3"] is True
    assert report.checks["ffmpeg"] is False


def test_healthz_deep_unhealthy_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unhealthy() -> ReadinessReport:
        return ReadinessReport(
            healthy=False,
            failed_service="s3",
            checks={
                "postgres": True,
                "redis": True,
                "s3": False,
                "ffmpeg": True,
                "celery": True,
            },
        )

    monkeypatch.setattr("app.api.health.check_deep_health", _unhealthy)

    response = client.get("/healthz/deep")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["failed_service"] == "s3"
    assert body["checks"]["s3"] is False


def test_readyz_unhealthy_returns_503_with_failed_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unhealthy() -> ReadinessReport:
        return ReadinessReport(
            healthy=False,
            failed_service="celery",
            checks={"postgres": True, "redis": True, "celery": False},
        )

    monkeypatch.setattr("app.api.health.check_readiness", _unhealthy)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "failed_service": "celery"}


def test_readyz_healthy_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _healthy() -> ReadinessReport:
        return ReadinessReport(
            healthy=True,
            failed_service=None,
            checks={"postgres": True, "redis": True, "celery": True},
        )

    monkeypatch.setattr("app.api.health.check_readiness", _healthy)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_celery_eager_mode_skips_worker_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.health import probes

    monkeypatch.setattr(
        probes,
        "get_settings",
        lambda: SimpleNamespace(celery_task_always_eager=True),
    )

    assert probes._celery_workers_ping_sync() is True
