"""Unit tests for highload indexes, Redis history cache, and Telegram alerts."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.generation import Generation
from app.models.generation_job import GenerationJob
from app.services import telegram_alerts


def test_generation_job_has_composite_history_indexes() -> None:
    index_names = {index.name for index in GenerationJob.__table__.indexes}
    assert "ix_generation_jobs_user_id_created_at" in index_names
    assert "ix_generation_jobs_user_id_status_created_at" in index_names


def test_legacy_generations_has_composite_history_index() -> None:
    index_names = {index.name for index in Generation.__table__.indexes}
    assert "ix_generations_user_id_created_at" in index_names


def test_extract_error_location_prefers_app_frame() -> None:
    def _raise_from_app() -> None:
        raise ValueError("boom")

    try:
        _raise_from_app()
    except ValueError as exc:
        location = telegram_alerts.extract_error_location(exc)

    assert location.lineno > 0
    assert location.func_name == "_raise_from_app"
    assert location.short_filename.endswith("test_highload_deploy.py") or "test_highload" in location.short_filename


@pytest.mark.asyncio
async def test_format_http_alert_includes_error_type_file_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RuntimeError("db down")

    try:
        _boom()
    except RuntimeError as exc:
        request = SimpleNamespace(
            method="GET",
            url=SimpleNamespace(path="/api/v1/generations/history"),
            state=SimpleNamespace(client_ip="1.2.3.4"),
        )
        monkeypatch.setattr(
            telegram_alerts,
            "get_settings",
            lambda: SimpleNamespace(
                cloudflare_trust_headers=False,
                trusted_proxy_cidrs="",
            ),
        )
        message = telegram_alerts._format_http_alert(request, exc)  # type: ignore[arg-type]

    assert "error_type: RuntimeError" in message
    assert "file:" in message
    assert "line:" in message
    assert "function: _boom" in message
    assert "path: /api/v1/generations/history" in message


@pytest.mark.asyncio
async def test_history_cache_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, dict] = {}

    async def fake_cache_json(key: str, payload: dict, ttl_seconds: int) -> None:
        assert ttl_seconds > 0
        store[key] = payload

    async def fake_get_cached_json(key: str) -> dict | None:
        return store.get(key)

    async def fake_delete_keys_by_prefix(prefix: str, *, scan_count: int = 100) -> int:
        keys = [key for key in list(store) if key.startswith(prefix)]
        for key in keys:
            del store[key]
        return len(keys)

    from app.infrastructure import generation_history_cache as cache_mod

    monkeypatch.setattr(cache_mod, "cache_json", fake_cache_json)
    monkeypatch.setattr(cache_mod, "get_cached_json", fake_get_cached_json)
    monkeypatch.setattr(cache_mod, "delete_keys_by_prefix", fake_delete_keys_by_prefix)
    monkeypatch.setattr(
        cache_mod,
        "get_settings",
        lambda: SimpleNamespace(generation_history_cache_ttl_seconds=30),
    )

    user_id = uuid4()
    items = [{"task_id": str(user_id), "status": "completed"}]
    await cache_mod.set_cached_generation_history(
        user_id=user_id,
        limit=50,
        offset=0,
        items=items,
    )
    cached = await cache_mod.get_cached_generation_history(
        user_id=user_id,
        limit=50,
        offset=0,
    )
    assert cached == items

    await cache_mod.invalidate_generation_history_cache(user_id)
    assert (
        await cache_mod.get_cached_generation_history(
            user_id=user_id,
            limit=50,
            offset=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_list_generation_history_uses_redis_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import generations as generations_api
    from app.domain.generation import GenerationJobStatus
    from app.models.enums import SubscriptionStatus
    from app.models.user import User

    user = User(
        id=uuid4(),
        email="cache@test.local",
        hashed_password="x",
        subscription_status=SubscriptionStatus.PRO,
    )
    cached_payload = [
        {
            "task_id": str(uuid4()),
            "status": GenerationJobStatus.COMPLETED.value,
            "progress": 100,
            "product_category": "electronics",
            "thumbnail_url": "https://cdn.test/t.jpg",
            "thumbnail_mime_type": "image/jpeg",
            "thumbnail_size_bytes": 1024,
            "archive_status": "expired",
            "archive_url": None,
            "archive_expires_at": None,
            "provider_used": "primary",
            "warning": None,
            "created_at": "2026-08-07T10:00:00+00:00",
            "completed_at": "2026-08-07T10:01:00+00:00",
        }
    ]

    async def fake_get_cached(**_kwargs: object) -> list[dict]:
        return cached_payload

    class ShouldNotHitRepository:
        def __init__(self, _session: object) -> None:
            raise AssertionError("DB must not be queried on cache hit")

    monkeypatch.setattr(
        generations_api,
        "get_cached_generation_history",
        fake_get_cached,
    )
    monkeypatch.setattr(generations_api, "GenerationRepository", ShouldNotHitRepository)

    response = await generations_api.list_generation_history(
        current_user=user,
        db_session=object(),  # type: ignore[arg-type]
        limit=50,
        offset=0,
    )
    assert len(response) == 1
    assert response[0].status == GenerationJobStatus.COMPLETED
