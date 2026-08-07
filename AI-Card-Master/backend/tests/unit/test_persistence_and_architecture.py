from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.domain.generation import GenerationErrorCode, GenerationErrorInfo
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.enums import PaymentStatus, TariffCode
from app.models.generation_job import GenerationJob
from app.models.payment import Payment
from app.models.user import User
from app.services.billing_service import BillingService, BillingValidationError
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


class FakeUserSession:
    def __init__(self, user: User) -> None:
        self.user = user
        self.commits = 0
        self.flushes = 0
        self.refreshes = 0

    async def get(
        self,
        model: type[Any],
        identity: Any,
        *,
        with_for_update: bool = False,
    ) -> Any:
        assert with_for_update is True
        if model is User and identity == self.user.id:
            return self.user
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, _: Any) -> None:
        self.refreshes += 1


class FakePaymentSession:
    def __init__(self, payment: Payment, user: User, referrer: User) -> None:
        self.payment = payment
        self.user = user
        self.referrer = referrer
        self.commits = 0
        self.refreshes = 0

    async def scalar(self, _statement: Any) -> Any:
        return self.payment

    async def get(
        self,
        model: type[Any],
        identity: Any,
        *,
        with_for_update: bool = False,
    ) -> Any:
        assert with_for_update is True
        if model is User and identity == self.user.id:
            return self.user
        if model is User and identity == self.referrer.id:
            return self.referrer
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _: Any) -> None:
        self.refreshes += 1


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


@pytest.mark.asyncio
async def test_final_failure_refunds_full_hd_face_fix_cost() -> None:
    user = User(
        id=uuid4(),
        email="hd-refund@example.com",
        hashed_password="hash",
        ai_coins=0,
    )
    job = GenerationJob(
        id=uuid4(),
        user_id=user.id,
        subscription_status="Pro",
        input_object_key="input/product.png",
        coin_charged=True,
        coins_charged=3,
        coin_refunded=False,
    )
    session = FakeRefundSession(job, user)
    repository = GenerationRepository(session)  # type: ignore[arg-type]
    error = GenerationErrorInfo(
        code=GenerationErrorCode.TRANSIENT,
        message="Face Fix unavailable.",
        retryable=True,
    )

    await repository.fail_job(job.id, error)
    await repository.fail_job(job.id, error)

    assert user.ai_coins == 3
    assert job.coin_refunded is True


@pytest.mark.asyncio
async def test_daily_bonus_claims_once_per_utc_day() -> None:
    user = User(
        id=uuid4(),
        email="daily@example.com",
        hashed_password="hash",
        ai_coins=0,
        daily_bonus_claimed_at=None,
        daily_bonus_streak=0,
    )
    session = FakeUserSession(user)
    billing = BillingService(session)  # type: ignore[arg-type]

    first = await billing.claim_daily_bonus(user.id)
    second = await billing.claim_daily_bonus(user.id)

    assert first.claimed is True
    assert first.coins_granted == 1
    assert second.claimed is False
    assert second.coins_granted == 0
    assert user.ai_coins == 1
    assert user.daily_bonus_streak == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_successful_payment_grants_referral_bonus_once() -> None:
    referrer = User(
        id=uuid4(),
        email="referrer@example.com",
        hashed_password="hash",
        ai_coins=2,
        referral_code="ABC123XY",
    )
    invited = User(
        id=uuid4(),
        email="invited@example.com",
        hashed_password="hash",
        ai_coins=0,
        referred_by_user_id=referrer.id,
        referral_bonus_granted_at=None,
    )
    payment = Payment(
        id=uuid4(),
        user_id=invited.id,
        tariff_code=TariffCode.START,
        yookassa_payment_id="yk_referral_1",
        amount_rub=Decimal("319.00"),
        status=PaymentStatus.PENDING,
    )
    session = FakePaymentSession(payment, invited, referrer)
    billing = BillingService(session)  # type: ignore[arg-type]

    first = await billing.apply_successful_payment(
        yookassa_payment_id=payment.yookassa_payment_id,
        expected_amount=Decimal("319.00"),
    )
    second = await billing.apply_successful_payment(
        yookassa_payment_id=payment.yookassa_payment_id,
        expected_amount=Decimal("319.00"),
    )

    assert first.already_processed is False
    assert second.already_processed is True
    assert referrer.ai_coins == 12
    assert invited.referral_bonus_granted_at is not None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_safe_spend_rejects_zero_balance_debit() -> None:
    user = User(
        id=uuid4(),
        email="empty@example.com",
        hashed_password="hash",
        ai_coins=0,
        daily_bonus_claimed_at=datetime(2026, 8, 6, tzinfo=UTC),
        daily_bonus_streak=1,
    )
    session = FakeUserSession(user)
    billing = BillingService(session)  # type: ignore[arg-type]

    with pytest.raises(BillingValidationError):
        await billing.debit_generation_coin(user.id)

    assert user.ai_coins == 0
    assert session.commits == 0


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
    forbidden_modules = {
        "fastapi",
        "celery",
        "redis",
        "sqlalchemy",
    }
    for source_path in application_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    assert root not in forbidden_modules, (
                        f"{source_path} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                # ``from app.infrastructure.redis import …`` still couples to redis.
                parts = node.module.split(".")
                assert "redis" not in parts, f"{source_path} imports {node.module}"
                assert root not in forbidden_modules, (
                    f"{source_path} imports {node.module}"
                )


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
