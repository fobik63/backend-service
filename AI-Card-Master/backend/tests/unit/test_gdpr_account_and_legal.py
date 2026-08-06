"""Unit tests for GDPR account erasure and public legal documents."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.application.account_service import (
    AccountService,
    AccountValidationError,
)
from app.core.config import Settings
from app.core.security import hash_password
from app.domain.account import ACCOUNT_DELETION_CONFIRMATION
from app.legal.documents import get_privacy_policy, get_terms_of_service
from app.main import app


class FakeAccountRepository:
    def __init__(self, *, email: str, password: str) -> None:
        self.user_id = uuid4()
        self.email = email
        self.hashed_password = hash_password(password)
        self.keys = ["users/a/input.png", "users/a/archive.zip", "users/a/input.png"]
        self.deleted = False

    async def get_user_credentials(self, user_id):
        if user_id != self.user_id or self.deleted:
            return None
        return self.email, self.hashed_password

    async def collect_storage_object_keys(self, user_id):
        assert user_id == self.user_id
        # Mimic repository dedupe expectation in service via returned list.
        return list(dict.fromkeys(self.keys))

    async def delete_user(self, user_id) -> bool:
        if user_id != self.user_id or self.deleted:
            return False
        self.deleted = True
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
async def test_delete_account_requires_exact_confirmation() -> None:
    repo = FakeAccountRepository(email="u@example.com", password="secret-pass")
    service = AccountService(repo, FakeStorage())

    with pytest.raises(AccountValidationError, match="Confirmation must be exactly"):
        await service.delete_account(
            user_id=repo.user_id,
            password="secret-pass",
            confirmation="delete",
        )


@pytest.mark.asyncio
async def test_delete_account_rejects_invalid_password() -> None:
    repo = FakeAccountRepository(email="u@example.com", password="secret-pass")
    service = AccountService(repo, FakeStorage())

    with pytest.raises(AccountValidationError, match="Invalid password"):
        await service.delete_account(
            user_id=repo.user_id,
            password="wrong",
            confirmation=ACCOUNT_DELETION_CONFIRMATION,
        )


@pytest.mark.asyncio
async def test_delete_account_wipes_storage_and_user() -> None:
    repo = FakeAccountRepository(email="u@example.com", password="secret-pass")
    storage = FakeStorage(fail_keys={"users/a/archive.zip"})
    invalidated: list = []

    async def invalidate(user_id) -> None:
        invalidated.append(user_id)

    service = AccountService(repo, storage, cache_invalidator=invalidate)
    result = await service.delete_account(
        user_id=repo.user_id,
        password="secret-pass",
        confirmation=ACCOUNT_DELETION_CONFIRMATION,
    )

    assert result.email == "u@example.com"
    assert result.storage_objects_deleted == 1
    assert result.storage_objects_failed == 1
    assert repo.deleted is True
    assert invalidated == [repo.user_id]
    assert storage.deleted == ["users/a/input.png"]


def test_legal_documents_render_operator_placeholders() -> None:
    settings = Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ai_card_master_test",
        JWT_SECRET_KEY="x" * 64,
        STABLE_DIFFUSION_API_KEY="test-stability-key",
        SERVICE_DISPLAY_NAME="AI-Card-Master",
        LEGAL_OPERATOR_NAME="ООО Тест Оператор",
        LEGAL_OPERATOR_ADDRESS="г. Москва, ул. Примерная, д. 1",
        SUPPORT_EMAIL="help@test.example",
        PRIVACY_EMAIL="privacy@test.example",
        PUBLIC_SITE_URL="https://test.example",
        LEGAL_DOCUMENTS_EFFECTIVE_DATE="2026-08-07",
    )

    terms = get_terms_of_service(settings=settings)
    privacy = get_privacy_policy(settings=settings)

    assert "ООО Тест Оператор" in terms
    assert "DELETE /api/v1/account" in terms
    assert "help@test.example" in terms
    assert "GDPR" in privacy
    assert "DELETE /api/v1/account" in privacy
    assert "ЮKassa" in privacy
    assert "[УКАЖИТЕ" not in terms
    assert "[УКАЖИТЕ" not in privacy


def test_legal_and_account_routes_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/legal/terms"]
    assert "get" in paths["/api/v1/legal/privacy"]
    assert "delete" in paths["/api/v1/account"]
