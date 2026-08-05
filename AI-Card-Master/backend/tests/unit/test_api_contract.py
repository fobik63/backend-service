from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.api.generations as generations_api
from app.main import app
from app.models.enums import SubscriptionStatus
from app.models.user import User


def test_generation_and_webhook_contracts_are_exposed() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/generations" in paths
    assert "post" in paths["/api/v1/generations"]
    assert "202" in paths["/api/v1/generations"]["post"]["responses"]
    assert "/api/v1/generations/{task_id}" in paths
    assert "get" in paths["/api/v1/generations/{task_id}"]
    assert "/api/v1/webhooks/midjourney/{provider_name}" in paths
    assert "post" in paths["/api/v1/webhooks/midjourney/{provider_name}"]


def test_liveness_and_dependency_readiness_are_separate() -> None:
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths


@pytest.mark.asyncio
async def test_status_polling_falls_back_to_db_when_redis_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        email="status@example.com",
        hashed_password="hash",
        subscription_status=SubscriptionStatus.PRO,
    )
    task_id = uuid4()
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=task_id,
        status="waiting_webhook",
        progress=25,
        provider_used="primary",
        warning=None,
        archive_object_key=None,
        slides=[],
        error_code=None,
        error_message=None,
        error_retryable=False,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    class Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_job_for_user(self, job_id: object, user_id: object) -> object:
            assert job_id == task_id
            assert user_id == user.id
            return job

    async def redis_down(_key: str) -> dict[str, object] | None:
        raise generations_api.RedisUnavailableError("redis unavailable")

    async def cache_down(*args: object, **kwargs: object) -> None:
        raise generations_api.RedisUnavailableError("redis unavailable")

    monkeypatch.setattr(generations_api, "GenerationRepository", Repository)
    monkeypatch.setattr(generations_api, "get_cached_json", redis_down)
    monkeypatch.setattr(generations_api, "cache_json", cache_down)
    monkeypatch.setattr(
        generations_api,
        "get_s3_storage",
        lambda: (_ for _ in ()).throw(
            generations_api.S3StorageConfigurationError("not configured")
        ),
    )

    response = await generations_api.get_generation_status(
        task_id=task_id,
        current_user=user,
        db_session=object(),  # type: ignore[arg-type]
    )

    assert response.task_id == task_id
    assert response.status.value == "waiting_webhook"
    assert response.progress == 25
