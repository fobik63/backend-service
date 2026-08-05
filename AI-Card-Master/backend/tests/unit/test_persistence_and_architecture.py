from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.domain.generation import GenerationErrorCode, GenerationErrorInfo
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.generation_job import GenerationJob
from app.models.user import User
from app.workers import generation_tasks


class FakeRefundSession:
    def __init__(self, job: GenerationJob, user: User) -> None:
        self.job = job
        self.user = user
        self.added: list[Any] = []
        self.commits = 0

    async def get(
        self,
        model: type[Any],
        identity: Any,
        *,
        with_for_update: bool = False,
    ) -> Any:
        if model is GenerationJob and identity == self.job.id:
            return self.job
        if model is User and identity == self.user.id:
            return self.user
        return None

    async def scalars(self, statement: Any) -> list[Any]:
        return []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_final_failure_refunds_coin_exactly_once() -> None:
    user = User(
        id=uuid4(),
        email="refund@example.com",
        hashed_password="hash",
        ai_coins=2,
    )
    job = GenerationJob(
        id=uuid4(),
        user_id=user.id,
        subscription_status="Pro",
        input_object_key="input/product.png",
        coin_charged=True,
        coin_refunded=False,
    )
    session = FakeRefundSession(job, user)
    repository = GenerationRepository(session)  # type: ignore[arg-type]
    error = GenerationErrorInfo(
        code=GenerationErrorCode.TRANSIENT,
        message="Providers are unavailable.",
        retryable=True,
    )

    await repository.fail_job(job.id, error)
    await repository.fail_job(job.id, error)

    assert user.ai_coins == 3
    assert job.coin_refunded is True
    assert session.commits == 2


def test_alembic_has_single_async_pipeline_head() -> None:
    migration = Path("alembic/versions/20260806_0003_async_generation_pipeline.py")
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    assignments: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            assignments[node.target.id] = node.value.value

    assert assignments["revision"] == "20260806_0003"
    assert assignments["down_revision"] == "20260806_0002"


def test_application_layer_has_no_framework_or_orm_imports() -> None:
    application_root = Path("app/application")
    forbidden = (
        "from fastapi",
        "import fastapi",
        "from celery",
        "import celery",
        "from redis",
        "import redis",
        "from sqlalchemy",
        "import sqlalchemy",
    )
    for source_path in application_root.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8").lower()
        for marker in forbidden:
            assert marker not in source, f"{source_path} imports {marker}"


def test_worker_and_use_case_do_not_use_blocking_sleep() -> None:
    sources = [
        Path("app/workers/generation_tasks.py"),
        Path("app/application/generation_service.py"),
    ]
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        assert "time.sleep(" not in source


def test_celery_task_executes_in_eager_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation_tasks, "_run_async", lambda _factory: 7)

    result = generation_tasks.dispatch_outbox_task.apply()

    assert result.successful()
    assert result.get() == 7
