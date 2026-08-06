"""Unit tests for Zero-Knowledge source retention purge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.source_retention_service import SourceRetentionService
from app.domain.source_retention import (
    SourceAssetCandidate,
    SourceRetentionStatus,
)
from app.infrastructure.celery_app import celery_app
from app.main import app


class FakeRetentionRepository:
    def __init__(self, candidates: list[SourceAssetCandidate]) -> None:
        self.candidates = candidates
        self.marked: list[tuple[str, object]] = []

    async def list_purge_candidates(self, *, cutoff, limit):
        assert cutoff.tzinfo is not None
        return self.candidates[:limit]

    async def mark_generation_input_deleted(self, *, job_id) -> bool:
        self.marked.append(("generation_input", job_id))
        return True

    async def mark_generation_archive_deleted(self, *, job_id) -> bool:
        self.marked.append(("generation_archive", job_id))
        return True

    async def mark_bulk_zip_deleted(self, *, batch_id) -> bool:
        self.marked.append(("bulk_zip", batch_id))
        return True

    async def mark_bulk_item_input_deleted(self, *, item_id) -> bool:
        self.marked.append(("bulk_item_input", item_id))
        return True

    async def mark_smart_variant_source_deleted(self, *, sync_id) -> bool:
        self.marked.append(("smart_variant_source", sync_id))
        return True


class FakeStorage:
    def __init__(self, *, fail_keys: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self.fail_keys = fail_keys or set()

    async def delete_object(self, *, object_key: str) -> None:
        if object_key in self.fail_keys:
            raise RuntimeError(f"boom:{object_key}")
        self.deleted.append(object_key)


@pytest.mark.asyncio
async def test_purge_deletes_heavy_assets_and_marks_deleted() -> None:
    job_id = uuid4()
    batch_id = uuid4()
    repo = FakeRetentionRepository(
        [
            SourceAssetCandidate(
                kind="generation_input",
                record_id=job_id,
                object_key="users/a/input.png",
                field_name="input_object_key",
            ),
            SourceAssetCandidate(
                kind="generation_archive",
                record_id=job_id,
                object_key="users/a/archive.zip",
                field_name="archive_object_key",
            ),
            SourceAssetCandidate(
                kind="bulk_zip",
                record_id=batch_id,
                object_key="bulk/a.zip",
                field_name="source_zip_object_key",
            ),
        ]
    )
    storage = FakeStorage()
    service = SourceRetentionService(repo, storage, retention_hours=24, batch_limit=50)

    result = await service.purge_expired_sources(
        now=datetime.now(UTC),
    )

    assert result.candidates == 3
    assert result.objects_deleted == 3
    assert result.objects_failed == 0
    assert result.records_marked_deleted == 3
    assert storage.deleted == [
        "users/a/input.png",
        "users/a/archive.zip",
        "bulk/a.zip",
    ]
    assert [kind for kind, _ in repo.marked] == [
        "generation_input",
        "generation_archive",
        "bulk_zip",
    ]


@pytest.mark.asyncio
async def test_purge_skips_db_mark_when_s3_delete_fails() -> None:
    job_id = uuid4()
    repo = FakeRetentionRepository(
        [
            SourceAssetCandidate(
                kind="generation_archive",
                record_id=job_id,
                object_key="users/a/bad.zip",
                field_name="archive_object_key",
            ),
            SourceAssetCandidate(
                kind="generation_input",
                record_id=job_id,
                object_key="users/a/ok.png",
                field_name="input_object_key",
            ),
        ]
    )
    storage = FakeStorage(fail_keys={"users/a/bad.zip"})
    service = SourceRetentionService(repo, storage, retention_hours=24)

    result = await service.purge_expired_sources(
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert result.objects_deleted == 1
    assert result.objects_failed == 1
    assert result.records_marked_deleted == 1
    assert result.failed_keys == ["users/a/bad.zip"]
    assert storage.deleted == ["users/a/ok.png"]
    assert repo.marked == [("generation_input", job_id)]


def test_source_retention_status_enum_values() -> None:
    assert SourceRetentionStatus.AVAILABLE.value == "available"
    assert SourceRetentionStatus.DELETED.value == "deleted"


def test_purge_task_is_registered_in_celery_beat() -> None:
    import app.workers.source_retention_tasks  # noqa: F401 — register task

    assert "privacy.purge_expired_sources" in celery_app.tasks
    assert "privacy-purge-expired-sources" in celery_app.conf.beat_schedule
    entry = celery_app.conf.beat_schedule["privacy-purge-expired-sources"]
    assert entry["task"] == "privacy.purge_expired_sources"


def test_account_delete_and_retention_routes_present() -> None:
    paths = app.openapi()["paths"]
    assert "delete" in paths["/api/v1/account"]
    assert "get" in paths["/api/v1/legal/privacy"]


def test_retention_window_helper_matches_config_default() -> None:
    from app.api import generations as generations_api

    assert generations_api._archive_retention() == timedelta(hours=24)
