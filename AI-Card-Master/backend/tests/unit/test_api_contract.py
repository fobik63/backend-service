from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

import app.api.generations as generations_api
from app.main import app
from app.models.enums import SubscriptionStatus
from app.models.user import User
from app.services.model_vto import ModelTypage, build_model_vto_task


def test_generation_and_webhook_contracts_are_exposed() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/generations" in paths
    assert "post" in paths["/api/v1/generations"]
    assert "202" in paths["/api/v1/generations"]["post"]["responses"]
    assert "/api/v1/generations/model" in paths
    assert "post" in paths["/api/v1/generations/model"]
    assert "202" in paths["/api/v1/generations/model"]["post"]["responses"]
    assert "/api/v1/generations/history" in paths
    assert "get" in paths["/api/v1/generations/history"]
    assert "/api/v1/generations/{task_id}" in paths
    assert "get" in paths["/api/v1/generations/{task_id}"]
    assert "/api/v1/generation-texts/{task_id}" in paths
    assert "get" in paths["/api/v1/generation-texts/{task_id}"]
    assert "/api/v1/webhooks/midjourney/{provider_name}" in paths
    assert "post" in paths["/api/v1/webhooks/midjourney/{provider_name}"]


def test_liveness_and_dependency_readiness_are_separate() -> None:
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths


def test_model_vto_task_preserves_garment_and_typage_prompt() -> None:
    task = build_model_vto_task(
        typage=ModelTypage(
            height_cm=178,
            body_type="athletic",
            ethnicity="mixed",
        ),
        background="neutral white studio",
        pose="three-quarter catalog pose",
    )

    assert task.slide_key == "model"
    assert task.selected_style == "virtual try-on photorealistic fashion model"
    assert "Transfer the exact clothing item" in task.user_text
    assert "178 cm tall" in task.user_text
    assert "athletic body build" in task.user_text
    assert "mixed ethnicity appearance" in task.user_text
    assert "neutral white studio" in task.user_text


def test_model_mode_rejects_source_key_from_another_user() -> None:
    owner_id = uuid4()
    other_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        generations_api._validate_owned_source_object_key(
            f"generation-inputs/{other_id}/source.png",
            owner_id,
        )

    assert exc_info.value.status_code == 403


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
        marketplace_text={
            "title": "SEO заголовок для маркетплейса с ключевыми словами",
            "description": " ".join(["Продающее описание товара для WB и Ozon"] * 40),
            "characteristics": (
                "Оптимизированная визуальная подача",
                "Подходит для карточки товара",
                "Выделяет ключевые преимущества",
            ),
        },
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
    assert response.marketplace_text is not None
    assert response.marketplace_text.title.startswith("SEO заголовок")


@pytest.mark.asyncio
async def test_generation_history_returns_thumbnail_and_expires_old_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        email="history@example.com",
        hashed_password="hash",
        subscription_status=SubscriptionStatus.PRO,
    )
    fresh_id = uuid4()
    expired_id = uuid4()
    now = datetime.now(UTC)
    jobs = (
        SimpleNamespace(
            id=fresh_id,
            status="completed",
            progress=100,
            product_category="shoes",
            thumbnail_object_key="previews/fresh.jpg",
            thumbnail_mime_type="image/jpeg",
            thumbnail_size_bytes=12_000,
            archive_object_key="archives/fresh.zip",
            provider_used="primary",
            warning=None,
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            id=expired_id,
            status="completed",
            progress=100,
            product_category="bags",
            thumbnail_object_key="previews/expired.jpg",
            thumbnail_mime_type="image/jpeg",
            thumbnail_size_bytes=10_000,
            archive_object_key="archives/expired.zip",
            provider_used="primary",
            warning=None,
            created_at=now - timedelta(days=2),
            completed_at=now - timedelta(hours=25),
        ),
    )

    class Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def list_generation_history_for_user(
            self,
            *,
            user_id: object,
            limit: int,
            offset: int,
        ) -> object:
            assert user_id == user.id
            assert limit == 50
            assert offset == 0
            return jobs

    class Storage:
        async def generate_presigned_url(self, *, object_key: str) -> str:
            return f"https://storage.test/{object_key}"

    monkeypatch.setattr(generations_api, "GenerationRepository", Repository)
    monkeypatch.setattr(generations_api, "get_s3_storage", Storage)

    response = await generations_api.list_generation_history(
        current_user=user,
        db_session=object(),  # type: ignore[arg-type]
    )

    assert [item.task_id for item in response] == [fresh_id, expired_id]
    assert response[0].thumbnail_url == "https://storage.test/previews/fresh.jpg"
    assert response[0].archive_status == "available"
    assert response[0].archive_url == "https://storage.test/archives/fresh.zip"
    assert response[1].thumbnail_url == "https://storage.test/previews/expired.jpg"
    assert response[1].archive_status == "expired"
    assert response[1].archive_url is None
