"""Unit tests for marketplace publish credentials and WB/Ozon publish flow."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx

from app.application.marketplace_publish_service import MarketplacePublishService
from app.core.credential_crypto import decrypt_secret_value, encrypt_secret_value
from app.domain.marketplace_publish import (
    CredentialValidationResult,
    MarketplacePublishNotFoundError,
    MarketplacePublishUpstreamError,
    MarketplacePublishValidationError,
    OzonPublishRequest,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    UserMarketplaceCredentialsInput,
    UserMarketplaceCredentialsView,
    WbPublishRequest,
)
from app.infrastructure.marketplaces.ozon_client import OzonSellerClient
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient


def test_encrypt_secret_roundtrip() -> None:
    secret = "unit-test-publish-secret"
    token = encrypt_secret_value("wb-token-xyz", secret=secret)
    assert token.startswith("aes256gcm.v1.")
    assert decrypt_secret_value(token, secret=secret) == "wb-token-xyz"


class FakeCredentialsRepo:
    def __init__(self) -> None:
        self.secret = "unit-test-publish-secret"
        self.store: dict[str, str | None] = {
            "wb_api_token": None,
            "ozon_client_id": None,
            "ozon_api_key": None,
        }
        self.publications: list[PublishResultView] = []

    def encrypt_plain_secret(self, value: str) -> str:
        return encrypt_secret_value(value, secret=self.secret)

    async def get_credentials_view(self, user_id):
        return UserMarketplaceCredentialsView(
            wb_configured=bool(self.store["wb_api_token"]),
            ozon_configured=bool(
                self.store["ozon_client_id"] and self.store["ozon_api_key"]
            ),
            updated_at=datetime.now(UTC),
        )

    async def load_decrypted_secrets(self, user_id):
        return dict(self.store)

    async def save_encrypted_secrets(
        self,
        *,
        user_id,
        wb_api_token_ciphertext=None,
        ozon_client_id_ciphertext=None,
        ozon_api_key_ciphertext=None,
        clear_wb=False,
        clear_ozon=False,
    ):
        if clear_wb:
            self.store["wb_api_token"] = None
        elif wb_api_token_ciphertext is not None:
            self.store["wb_api_token"] = decrypt_secret_value(
                wb_api_token_ciphertext, secret=self.secret
            )
        if clear_ozon:
            self.store["ozon_client_id"] = None
            self.store["ozon_api_key"] = None
        else:
            if ozon_client_id_ciphertext is not None:
                self.store["ozon_client_id"] = decrypt_secret_value(
                    ozon_client_id_ciphertext, secret=self.secret
                )
            if ozon_api_key_ciphertext is not None:
                self.store["ozon_api_key"] = decrypt_secret_value(
                    ozon_api_key_ciphertext, secret=self.secret
                )
        return await self.get_credentials_view(user_id)

    async def save_publication(
        self,
        *,
        user_id,
        platform,
        product_id,
        status,
        message,
        external_task_id,
        error_logs,
        request_payload,
    ):
        row = PublishResultView(
            id=uuid4(),
            platform=platform,
            product_id=product_id,
            status=status,
            message=message,
            external_task_id=external_task_id,
            error_logs=error_logs,
            created_at=datetime.now(UTC),
        )
        self.publications.append(row)
        return row


class FakePublishClient:
    def __init__(self, platform: PublishPlatform) -> None:
        self.platform = platform
        self.valid = True
        self.publish_result: PublishResultView | None = None
        self.raise_upstream: MarketplacePublishUpstreamError | None = None

    async def validate_credentials(self, credentials: dict[str, str]):
        return CredentialValidationResult(
            platform=self.platform,
            is_valid=self.valid,
            message="ok" if self.valid else "bad",
        )

    async def publish(self, *, credentials, request):
        if self.raise_upstream is not None:
            raise self.raise_upstream
        assert self.publish_result is not None
        return self.publish_result

    async def list_products(self, *, credentials, limit: int = 50):
        return ()


@pytest.mark.asyncio
async def test_save_credentials_requires_both_ozon_fields() -> None:
    repo = FakeCredentialsRepo()
    service = MarketplacePublishService(
        repo,
        clients={
            PublishPlatform.WILDBERRIES: FakePublishClient(PublishPlatform.WILDBERRIES),
            PublishPlatform.OZON: FakePublishClient(PublishPlatform.OZON),
        },
    )
    with pytest.raises(MarketplacePublishValidationError):
        await service.save_credentials(
            user_id=uuid4(),
            payload=UserMarketplaceCredentialsInput(
                ozon_client_id="123",
                validate_credentials=False,
            ),
        )


@pytest.mark.asyncio
async def test_save_and_validate_credentials() -> None:
    repo = FakeCredentialsRepo()
    wb = FakePublishClient(PublishPlatform.WILDBERRIES)
    ozon = FakePublishClient(PublishPlatform.OZON)
    service = MarketplacePublishService(
        repo,
        clients={
            PublishPlatform.WILDBERRIES: wb,
            PublishPlatform.OZON: ozon,
        },
    )
    user_id = uuid4()
    view = await service.save_credentials(
        user_id=user_id,
        payload=UserMarketplaceCredentialsInput(
            wb_api_token="wb-token",
            ozon_client_id="cid",
            ozon_api_key="akey",
            validate_credentials=True,
        ),
    )
    assert view.wb_configured is True
    assert view.ozon_configured is True
    assert view.wb_valid is True
    assert view.ozon_valid is True


@pytest.mark.asyncio
async def test_publish_wb_persists_failed_status() -> None:
    repo = FakeCredentialsRepo()
    repo.store["wb_api_token"] = "token"
    wb = FakePublishClient(PublishPlatform.WILDBERRIES)
    wb.raise_upstream = MarketplacePublishUpstreamError(
        "media failed",
        error_logs=("HTTP 400: bad images",),
    )
    service = MarketplacePublishService(
        repo,
        clients={
            PublishPlatform.WILDBERRIES: wb,
            PublishPlatform.OZON: FakePublishClient(PublishPlatform.OZON),
        },
    )
    result = await service.publish_wb(
        user_id=uuid4(),
        request=WbPublishRequest(
            nm_id=123456,
            image_urls=("https://cdn.example.com/a.jpg",),
            seo_text="SEO text for the card " * 20,
        ),
    )
    assert result.status is PublishStatus.FAILED
    assert "HTTP 400" in result.error_logs[0]
    assert len(repo.publications) == 1


@pytest.mark.asyncio
async def test_publish_ozon_success_pending() -> None:
    repo = FakeCredentialsRepo()
    repo.store["ozon_client_id"] = "cid"
    repo.store["ozon_api_key"] = "akey"
    ozon = FakePublishClient(PublishPlatform.OZON)
    ozon.publish_result = PublishResultView(
        id=uuid4(),
        platform=PublishPlatform.OZON,
        product_id="99",
        status=PublishStatus.PENDING,
        message="queued",
        external_task_id="task-1",
    )
    service = MarketplacePublishService(
        repo,
        clients={
            PublishPlatform.WILDBERRIES: FakePublishClient(PublishPlatform.WILDBERRIES),
            PublishPlatform.OZON: ozon,
        },
    )
    result = await service.publish_ozon(
        user_id=uuid4(),
        request=OzonPublishRequest(
            product_id=99,
            image_urls=("https://cdn.example.com/b.jpg",),
            description="Ozon product description text.",
        ),
    )
    assert result.status is PublishStatus.PENDING
    assert result.external_task_id == "task-1"


@pytest.mark.asyncio
async def test_publish_requires_credentials() -> None:
    repo = FakeCredentialsRepo()
    service = MarketplacePublishService(
        repo,
        clients={
            PublishPlatform.WILDBERRIES: FakePublishClient(PublishPlatform.WILDBERRIES),
            PublishPlatform.OZON: FakePublishClient(PublishPlatform.OZON),
        },
    )
    with pytest.raises(MarketplacePublishNotFoundError):
        await service.publish_wb(
            user_id=uuid4(),
            request=WbPublishRequest(
                nm_id=1,
                image_urls=("https://cdn.example.com/a.jpg",),
                seo_text="text",
            ),
        )


@respx.mock
@pytest.mark.asyncio
async def test_wb_client_validate_and_publish() -> None:
    base = "https://content-api.wildberries.ru"
    respx.post(f"{base}/content/v2/get/cards/list").mock(
        side_effect=[
            httpx.Response(200, json={"cards": []}),  # validate
            httpx.Response(  # fetch for publish
                200,
                json={
                    "cards": [
                        {
                            "nmID": 777,
                            "vendorCode": "SKU-1",
                            "brand": "Brand",
                            "title": "Old title",
                            "description": "Old",
                            "characteristics": [],
                            "sizes": [{"techSize": "0", "wbSize": "", "skus": ["1"]}],
                            "dimensions": {
                                "length": 10,
                                "width": 10,
                                "height": 10,
                                "weightBrutto": 0.3,
                            },
                        }
                    ]
                },
            ),
        ]
    )
    respx.post(f"{base}/content/v2/cards/update").mock(
        return_value=httpx.Response(200, json={"error": False})
    )
    respx.post(f"{base}/content/v3/media/save").mock(
        return_value=httpx.Response(200, json={"error": False})
    )

    client = WildberriesSellerClient(base_url=base)
    validation = await client.validate_credentials({"api_token": "t"})
    assert validation.is_valid is True

    result = await client.publish(
        credentials={"api_token": "t"},
        request=WbPublishRequest(
            nm_id=777,
            image_urls=("https://cdn.example.com/1.jpg",),
            seo_text="New SEO description for the product card.",
            title="New title",
        ),
    )
    assert result.status is PublishStatus.PENDING
    assert result.product_id == "777"


@respx.mock
@pytest.mark.asyncio
async def test_ozon_client_publish() -> None:
    base = "https://api-seller.ozon.ru"
    respx.post(f"{base}/v1/warehouse/list").mock(
        return_value=httpx.Response(200, json={"result": []})
    )
    respx.post(f"{base}/v1/product/attributes/update").mock(
        return_value=httpx.Response(200, json={"result": {"task_id": 55}})
    )
    respx.post(f"{base}/v1/product/pictures/import").mock(
        return_value=httpx.Response(200, json={"result": True})
    )

    client = OzonSellerClient(base_url=base)
    validation = await client.validate_credentials(
        {"client_id": "1", "api_key": "secret"}
    )
    assert validation.is_valid is True

    result = await client.publish(
        credentials={"client_id": "1", "api_key": "secret"},
        request=OzonPublishRequest(
            product_id=42,
            image_urls=("https://cdn.example.com/ozon.jpg",),
            description="Updated Ozon description.",
        ),
    )
    assert result.status is PublishStatus.PENDING
    assert result.external_task_id == "55"
