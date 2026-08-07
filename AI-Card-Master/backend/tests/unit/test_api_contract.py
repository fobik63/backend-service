from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from starlette.requests import Request
import pytest

import app.api.generations as generations_api
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.main import app
from app.models.enums import SubscriptionStatus
from app.models.user import User
from app.services.model_vto import ModelTypage, build_model_vto_task


def _fake_request(path: str = "/api/v1/generations") -> Request:
    """Minimal ASGI request for direct handler calls under SlowAPI wrappers."""

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
    )


def test_generation_and_webhook_contracts_are_exposed() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/auth/register" in paths
    assert "post" in paths["/api/v1/auth/register"]
    assert "201" in paths["/api/v1/auth/register"]["post"]["responses"]
    assert "/api/v1/auth/login" in paths
    assert "post" in paths["/api/v1/auth/login"]
    assert "/api/v1/auth/me" in paths
    assert "get" in paths["/api/v1/auth/me"]
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
    assert "/api/v1/referrals/stats" in paths
    assert "get" in paths["/api/v1/referrals/stats"]
    assert "/api/v1/referrals/apply" in paths
    assert "post" in paths["/api/v1/referrals/apply"]
    assert "/api/v1/legal/terms" in paths
    assert "get" in paths["/api/v1/legal/terms"]
    assert "/api/v1/legal/privacy" in paths
    assert "get" in paths["/api/v1/legal/privacy"]
    assert "/api/v1/account" in paths
    assert "delete" in paths["/api/v1/account"]
    assert "200" in paths["/api/v1/account"]["delete"]["responses"]
    assert "/api/v1/workspaces" in paths
    assert "post" in paths["/api/v1/workspaces"]
    assert "/api/v1/workspaces/me" in paths
    assert "get" in paths["/api/v1/workspaces/me"]
    assert "/api/v1/workspaces/managers" in paths
    assert "post" in paths["/api/v1/workspaces/managers"]
    assert "/api/v1/workspaces/managers/{manager_user_id}" in paths
    assert "delete" in paths["/api/v1/workspaces/managers/{manager_user_id}"]
    assert "/api/v1/workspaces/shares" in paths
    assert "post" in paths["/api/v1/workspaces/shares"]
    assert "get" in paths["/api/v1/workspaces/shares"]
    assert "/api/v1/workspaces/shares/{share_id}" in paths
    assert "delete" in paths["/api/v1/workspaces/shares/{share_id}"]
    assert "/api/v1/exports/requirements/{platform}" in paths
    assert "get" in paths["/api/v1/exports/requirements/{platform}"]
    assert "/api/v1/exports/credentials" in paths
    assert "get" in paths["/api/v1/exports/credentials"]
    assert "/api/v1/exports/credentials/{platform}" in paths
    assert "put" in paths["/api/v1/exports/credentials/{platform}"]
    assert "delete" in paths["/api/v1/exports/credentials/{platform}"]
    assert "/api/v1/exports/validate" in paths
    assert "post" in paths["/api/v1/exports/validate"]
    assert "/api/v1/exports/{platform}" in paths
    assert "post" in paths["/api/v1/exports/{platform}"]
    assert "/api/v1/analytics/style-presets" in paths
    assert "get" in paths["/api/v1/analytics/style-presets"]
    assert "/api/v1/analytics/analyze-links" in paths
    assert "post" in paths["/api/v1/analytics/analyze-links"]
    assert "202" in paths["/api/v1/analytics/analyze-links"]["post"]["responses"]
    assert "/api/v1/analytics/analyze-links/{task_id}" in paths
    assert "get" in paths["/api/v1/analytics/analyze-links/{task_id}"]
    assert "/api/v1/winback/cancel-intent" in paths
    assert "post" in paths["/api/v1/winback/cancel-intent"]
    assert "/api/v1/winback/offer" in paths
    assert "get" in paths["/api/v1/winback/offer"]
    assert "/api/v1/winback/offer/{offer_id}/claim" in paths
    assert "post" in paths["/api/v1/winback/offer/{offer_id}/claim"]
    assert "/api/v1/winback/telegram" in paths
    assert "post" in paths["/api/v1/winback/telegram"]
    assert "/api/v1/bulk-generations" in paths
    assert "post" in paths["/api/v1/bulk-generations"]
    assert "202" in paths["/api/v1/bulk-generations"]["post"]["responses"]
    assert "/api/v1/bulk-generations/{batch_id}" in paths
    assert "get" in paths["/api/v1/bulk-generations/{batch_id}"]
    assert "/api/v1/bulk-generations/notifications" in paths
    assert "get" in paths["/api/v1/bulk-generations/notifications"]
    assert "/api/v1/smart-variants" in paths
    assert "post" in paths["/api/v1/smart-variants"]
    assert "202" in paths["/api/v1/smart-variants"]["post"]["responses"]
    assert "/api/v1/smart-variants/{sync_id}" in paths
    assert "get" in paths["/api/v1/smart-variants/{sync_id}"]
    assert "/api/v1/claude/reasoning/analyze" in paths
    assert "post" in paths["/api/v1/claude/reasoning/analyze"]
    assert "202" in paths["/api/v1/claude/reasoning/analyze"]["post"]["responses"]
    assert "/api/v1/claude/reasoning/{task_id}" in paths
    assert "get" in paths["/api/v1/claude/reasoning/{task_id}"]
    assert "/api/v1/claude-analyses" in paths
    assert "post" in paths["/api/v1/claude-analyses"]
    assert "202" in paths["/api/v1/claude-analyses"]["post"]["responses"]
    assert "/api/v1/claude-analyses/{analysis_id}" in paths
    assert "get" in paths["/api/v1/claude-analyses/{analysis_id}"]
    assert "/api/v1/oracle/preview" in paths
    assert "post" in paths["/api/v1/oracle/preview"]
    assert "/api/v1/oracle/predict" in paths
    assert "post" in paths["/api/v1/oracle/predict"]
    assert "202" in paths["/api/v1/oracle/predict"]["post"]["responses"]
    assert "/api/v1/oracle/notifications" in paths
    assert "get" in paths["/api/v1/oracle/notifications"]
    assert "/api/v1/oracle/{task_id}" in paths
    assert "get" in paths["/api/v1/oracle/{task_id}"]
    assert "/api/v1/ai-strategy/preview" in paths
    assert "post" in paths["/api/v1/ai-strategy/preview"]
    assert "/api/v1/ai-strategy/plan" in paths
    assert "post" in paths["/api/v1/ai-strategy/plan"]
    assert "202" in paths["/api/v1/ai-strategy/plan"]["post"]["responses"]
    assert "/api/v1/ai-strategy/{task_id}" in paths
    assert "get" in paths["/api/v1/ai-strategy/{task_id}"]
    assert "/api/v1/marketplace-bridge/dashboard" in paths
    assert "get" in paths["/api/v1/marketplace-bridge/dashboard"]
    assert "/api/v1/marketplace-bridge/platforms/{platform}" in paths
    assert "get" in paths["/api/v1/marketplace-bridge/platforms/{platform}"]
    style_schema = paths["/api/v1/analytics/style-presets"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert "$ref" in style_schema or "properties" in style_schema


def test_liveness_and_dependency_readiness_are_separate() -> None:
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/healthz" in paths
    assert "/readyz" in paths


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


def test_premium_engine_mode_requires_paid_subscription() -> None:
    user = User(
        id=uuid4(),
        email="free@example.com",
        hashed_password="hash",
        subscription_status=SubscriptionStatus.FREE,
    )

    with pytest.raises(HTTPException) as exc_info:
        generations_api._ensure_engine_mode_allowed(GenerationEngineMode.PREMIUM, user)

    assert exc_info.value.status_code == 403


def test_hd_face_fix_requires_paid_subscription() -> None:
    user = User(
        id=uuid4(),
        email="free-hd@example.com",
        hashed_password="hash",
        subscription_status=SubscriptionStatus.FREE,
    )

    with pytest.raises(HTTPException) as exc_info:
        generations_api._ensure_generation_options_allowed(
            GenerationEngineMode.PREMIUM,
            GenerationPostProcessingMode.HD_FACE_FIX,
            user,
        )

    assert exc_info.value.status_code == 403


def test_engine_mode_accepts_client_string_values() -> None:
    form = generations_api.GenerationForm.model_validate(
        {"engine_mode": "premium", "post_processing_mode": "hd_quality"}
    )
    payload = generations_api.ModelModeRequest.model_validate(
        {
            "source_image_object_key": f"user-uploads/{uuid4()}/source.png",
            "height_cm": 180,
            "body_type": "athletic",
            "ethnicity": "mixed",
            "engine_mode": "standard",
            "post_processing_mode": "fast_generation",
        }
    )

    assert form.engine_mode == GenerationEngineMode.PREMIUM
    assert form.post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX
    assert payload.engine_mode == GenerationEngineMode.STANDARD
    assert payload.post_processing_mode == GenerationPostProcessingMode.FAST


def test_hd_face_fix_forces_premium_engine_profile() -> None:
    assert (
        generations_api._effective_engine_mode(
            GenerationEngineMode.STANDARD,
            GenerationPostProcessingMode.HD_FACE_FIX,
        )
        == GenerationEngineMode.PREMIUM
    )


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

        async def get_detail_for_user(self, job_id: object, user_id: object) -> object:
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
        request=_fake_request(f"/api/v1/generations/{task_id}"),
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
            slides=[],
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
            slides=[],
        ),
    )
    summaries = tuple(
        SimpleNamespace(job=job, slide_count=5) for job in jobs
    )

    class Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def list_summary_for_user(
            self,
            *,
            user_id: object,
            limit: int,
            offset: int,
        ) -> object:
            assert user_id == user.id
            assert limit == 50
            assert offset == 0
            return summaries

    class Storage:
        async def generate_presigned_url(self, *, object_key: str) -> str:
            return f"https://storage.test/{object_key}"

    monkeypatch.setattr(generations_api, "GenerationRepository", Repository)
    monkeypatch.setattr(generations_api, "get_s3_storage", Storage)

    async def cache_miss(**_kwargs: object) -> None:
        return None

    async def cache_noop(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(generations_api, "get_cached_generation_history", cache_miss)
    monkeypatch.setattr(generations_api, "set_cached_generation_history", cache_noop)

    response = await generations_api.list_generation_history(
        request=_fake_request("/api/v1/generations/history"),
        current_user=user,
        db_session=object(),  # type: ignore[arg-type]
    )

    assert [item.task_id for item in response] == [fresh_id, expired_id]
    assert response[0].slide_count == 5
    assert response[0].thumbnail_url == "https://storage.test/previews/fresh.jpg"
    assert response[0].archive_status == "available"
    assert response[0].archive_url == "https://storage.test/archives/fresh.zip"
    assert response[1].thumbnail_url == "https://storage.test/previews/expired.jpg"
    assert response[1].archive_status == "expired"
    assert response[1].archive_url is None
