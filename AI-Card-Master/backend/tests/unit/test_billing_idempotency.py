"""Unit tests: Redis → Postgres double-check for financial idempotency."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import fakeredis
import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure import idempotency_store as store_module
from app.infrastructure import redis as redis_module
from app.infrastructure.idempotency_store import STATUS_COMPLETED
from app.models.idempotency_record import IdempotencyRecord
from app.services.billing_service import (
    BillingService,
    BillingValidationError,
    IdempotentCoinMutationResult,
    billing_idempotency_scope,
)


def _settings(**overrides: Any) -> SimpleNamespace:
    data: dict[str, Any] = {
        "idempotency_response_ttl_seconds": 900,
        "referral_bonus_coins": 10,
        "daily_bonus_coins": 1,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class _FakeSession:
    """Minimal AsyncSession stand-in for billing idempotency unit tests."""

    def __init__(self) -> None:
        self.users: dict = {}
        self.records: dict[str, IdempotencyRecord] = {}
        self.flushed = 0
        self.added: list[object] = []
        self._pending_record: IdempotencyRecord | None = None

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, IdempotencyRecord):
            if obj.idempotency_key in self.records:
                raise IntegrityError("duplicate", params=None, orig=Exception())
            self._pending_record = obj

    async def flush(self) -> None:
        self.flushed += 1
        pending = self._pending_record
        if pending is not None:
            if pending.idempotency_key in self.records:
                self._pending_record = None
                raise IntegrityError("duplicate", params=None, orig=Exception())
            self.records[pending.idempotency_key] = pending
            self._pending_record = None

    async def get(self, model, key, with_for_update=False):  # noqa: ANN001
        if model is IdempotencyRecord:
            return self.records.get(key)
        return self.users.get(key)

    def begin_nested(self) -> _Nested:
        return _Nested(self)


class _Nested:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is not None:
            self._session._pending_record = None
            return False
        pending = self._session._pending_record
        if pending is not None:
            self._session.records[pending.idempotency_key] = pending
            self._session._pending_record = None
        return False


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeAsyncRedis:
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    monkeypatch.setattr(redis_module, "get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def billing_settings(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    settings = _settings()
    monkeypatch.setattr(
        "app.services.billing_service.get_settings",
        lambda: settings,
    )
    return settings


@pytest.mark.asyncio
async def test_debit_writes_postgres_idempotency_in_same_flush(
    fake_redis: fakeredis.FakeAsyncRedis,
    billing_settings: SimpleNamespace,
) -> None:
    _ = fake_redis, billing_settings
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=10)
    session = _FakeSession()
    session.users[user_id] = user

    billing = BillingService(session)  # type: ignore[arg-type]
    result = await billing.debit_coins_idempotent_in_transaction(
        user_id=user_id,
        amount=3,
        idempotency_key="charge-key-001",
        response_body={"source": "unit"},
    )

    assert result.already_processed is False
    assert user.ai_coins == 7
    assert "charge-key-001" in session.records
    record = session.records["charge-key-001"]
    assert record.user_id == user_id
    assert record.response_code == 200
    assert record.response_body["amount"] == 3
    assert record.response_body["new_balance"] == 7
    assert record.response_body["source"] == "unit"


@pytest.mark.asyncio
async def test_debit_replays_from_postgres_when_redis_misses(
    fake_redis: fakeredis.FakeAsyncRedis,
    billing_settings: SimpleNamespace,
) -> None:
    _ = billing_settings
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=7)
    session = _FakeSession()
    session.users[user_id] = user
    session.records["charge-key-002"] = IdempotencyRecord(
        idempotency_key="charge-key-002",
        user_id=user_id,
        response_code=200,
        response_body={
            "operation": "debit",
            "amount": 3,
            "new_balance": 7,
            "source": "unit",
        },
    )

    await fake_redis.flushdb()

    billing = BillingService(session)  # type: ignore[arg-type]
    result = await billing.debit_coins_idempotent_in_transaction(
        user_id=user_id,
        amount=3,
        idempotency_key="charge-key-002",
    )

    assert result.already_processed is True
    assert user.ai_coins == 7
    assert result.response_body["new_balance"] == 7

    cached = await store_module.get_idempotency_record(
        scope=billing_idempotency_scope(user_id),
        idempotency_key="charge-key-002",
    )
    assert cached is not None
    assert cached["status"] == STATUS_COMPLETED


@pytest.mark.asyncio
async def test_debit_replays_from_redis_without_touching_balance(
    fake_redis: fakeredis.FakeAsyncRedis,
    billing_settings: SimpleNamespace,
) -> None:
    _ = billing_settings
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=7)
    session = _FakeSession()
    session.users[user_id] = user

    body = {"operation": "debit", "amount": 3, "new_balance": 7}
    await store_module.store_completed_response(
        scope=billing_idempotency_scope(user_id),
        idempotency_key="charge-key-003",
        status_code=200,
        body=json.dumps(body),
        media_type="application/json",
        ttl_seconds=900,
    )

    billing = BillingService(session)  # type: ignore[arg-type]
    result = await billing.debit_coins_idempotent_in_transaction(
        user_id=user_id,
        amount=3,
        idempotency_key="charge-key-003",
    )

    assert isinstance(result, IdempotentCoinMutationResult)
    assert result.already_processed is True
    assert user.ai_coins == 7
    assert session.records == {}


@pytest.mark.asyncio
async def test_debit_without_key_unchanged(
    fake_redis: fakeredis.FakeAsyncRedis,
    billing_settings: SimpleNamespace,
) -> None:
    _ = fake_redis, billing_settings
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=5)
    session = _FakeSession()
    session.users[user_id] = user

    billing = BillingService(session)  # type: ignore[arg-type]
    user_out = await billing.debit_coins_in_transaction(user_id=user_id, amount=2)
    assert user_out.ai_coins == 3
    assert session.records == {}


@pytest.mark.asyncio
async def test_idempotency_key_foreign_user_rejected(
    fake_redis: fakeredis.FakeAsyncRedis,
    billing_settings: SimpleNamespace,
) -> None:
    _ = fake_redis, billing_settings
    owner = uuid4()
    other = uuid4()
    session = _FakeSession()
    session.users[other] = SimpleNamespace(id=other, ai_coins=50)
    session.records["shared-key"] = IdempotencyRecord(
        idempotency_key="shared-key",
        user_id=owner,
        response_code=200,
        response_body={"amount": 1},
    )

    billing = BillingService(session)  # type: ignore[arg-type]
    with pytest.raises(BillingValidationError, match="another user"):
        await billing.debit_coins_idempotent_in_transaction(
            user_id=other,
            amount=1,
            idempotency_key="shared-key",
        )


@pytest.mark.asyncio
async def test_hold_coins_idempotent_replay_returns_same_transaction_id() -> None:
    from app.core.pricing import BillingService as PricingBilling
    from app.models.coin_hold import CoinHold

    user_id = uuid4()
    prior_tx = uuid4()
    balances = {user_id: 40}
    holds: dict = {}

    class _Wallet:
        def __init__(self) -> None:
            self._replayed = False

        async def lookup_idempotency(self, *, user_id, idempotency_key):  # noqa: ANN001
            if idempotency_key == "hold-key-1" and self._replayed:
                return IdempotentCoinMutationResult(
                    user=SimpleNamespace(ai_coins=balances[user_id]),
                    already_processed=True,
                    response_code=200,
                    response_body={"transaction_id": str(prior_tx)},
                    idempotency_key=idempotency_key,
                )
            return None

        async def debit_coins_idempotent_in_transaction(self, **kwargs):  # noqa: ANN003
            amount = kwargs["amount"]
            balances[kwargs["user_id"]] -= amount
            self._replayed = True
            body = dict(kwargs.get("response_body") or {})
            return IdempotentCoinMutationResult(
                user=SimpleNamespace(ai_coins=balances[kwargs["user_id"]]),
                already_processed=False,
                response_code=200,
                response_body=body,
                idempotency_key=kwargs.get("idempotency_key"),
            )

    class _Session:
        def add(self, obj: CoinHold) -> None:
            holds[obj.id] = obj

        def delete(self, obj: CoinHold) -> None:
            holds.pop(obj.id, None)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def refresh(self, obj: CoinHold) -> None:
            return None

        async def get(self, model, key, with_for_update=False):  # noqa: ANN001
            return holds.get(key)

    session = _Session()
    billing = PricingBilling(session, settings=_settings())  # type: ignore[arg-type]
    billing._wallet = _Wallet()  # type: ignore[method-assign]

    tx1 = await billing.hold_coins(
        user_id, 10, service_type="three_d", idempotency_key="hold-key-1"
    )
    assert balances[user_id] == 30
    assert tx1 in holds

    tx2 = await billing.hold_coins(
        user_id, 10, service_type="three_d", idempotency_key="hold-key-1"
    )
    assert tx2 == prior_tx
    assert balances[user_id] == 30
