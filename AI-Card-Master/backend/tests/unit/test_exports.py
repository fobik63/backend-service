"""Unit tests for Direct Export validation and one-click draft workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.export_service import (
    ExportNotFoundError,
    ExportService,
    ExportValidationError,
)
from app.core.credential_crypto import decrypt_credentials, encrypt_credentials
from app.domain.export import (
    ExportStatus,
    ImageAssetMeta,
    MarketplaceCredentialView,
    MarketplacePlatform,
    ExportResultView,
    validate_card_for_marketplace,
)
from app.domain.generation import MarketplaceTextContent


def _valid_title(platform: MarketplacePlatform) -> str:
    if platform is MarketplacePlatform.WILDBERRIES:
        return "Кроссовки мужские беговые летние"
    if platform is MarketplacePlatform.OZON:
        return "Кроссовки мужские беговые легкие для повседневной носки"
    return "Mens running sneakers lightweight everyday comfort trainers"


def _valid_description(platform: MarketplacePlatform) -> str:
    base = (
        "Продающее описание товара с ключевыми преимуществами, материалами, "
        "сценариями использования и уходом. "
    )
    if platform is MarketplacePlatform.WILDBERRIES:
        return (base * 20)[:1200]
    if platform is MarketplacePlatform.OZON:
        return (base * 5)[:400]
    return (base * 3)[:200]


def _portrait_images(count: int = 5) -> tuple[ImageAssetMeta, ...]:
    return tuple(
        ImageAssetMeta(
            object_key=f"slides/{index}.jpg",
            width=900,
            height=1200,
            size_bytes=250_000,
            format="JPEG",
        )
        for index in range(count)
    )


def test_wildberries_rejects_short_title_and_low_resolution() -> None:
    report = validate_card_for_marketplace(
        platform=MarketplacePlatform.WILDBERRIES,
        title="Short",
        description=_valid_description(MarketplacePlatform.WILDBERRIES),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
        images=(
            ImageAssetMeta(
                object_key="a.jpg",
                width=400,
                height=500,
                size_bytes=10_000,
                format="JPEG",
            ),
        ),
    )
    codes = {issue.code for issue in report.errors}
    assert not report.is_valid
    assert "TITLE_TOO_SHORT" in codes
    assert "PHOTO_RESOLUTION_TOO_LOW" in codes


def test_ozon_rejects_too_many_photos() -> None:
    report = validate_card_for_marketplace(
        platform=MarketplacePlatform.OZON,
        title=_valid_title(MarketplacePlatform.OZON),
        description=_valid_description(MarketplacePlatform.OZON),
        characteristics=("A", "B", "C"),
        images=_portrait_images(16),
    )
    assert not report.is_valid
    assert any(issue.code == "PHOTOS_TOO_MANY" for issue in report.errors)


def test_amazon_accepts_square_photos_and_warns_on_low_zoom() -> None:
    report = validate_card_for_marketplace(
        platform=MarketplacePlatform.AMAZON,
        title=_valid_title(MarketplacePlatform.AMAZON),
        description=_valid_description(MarketplacePlatform.AMAZON),
        characteristics=("Soft sole", "Breathable mesh", "Everyday style"),
        images=(
            ImageAssetMeta(
                object_key="main.jpg",
                width=800,
                height=800,
                size_bytes=180_000,
                format="JPEG",
            ),
        ),
    )
    assert report.is_valid
    assert any(issue.code == "AMAZON_RESOLUTION_RECOMMENDATION" for issue in report.warnings)


def test_credential_roundtrip_encryption() -> None:
    secret = "unit-test-marketplace-secret"
    payload = {"api_token": "wb-token-123"}
    token = encrypt_credentials(payload, secret=secret)
    assert token.startswith("aes256gcm.v1.")
    assert decrypt_credentials(token, secret=secret) == payload


class FakeExportRepository:
    def __init__(self) -> None:
        self.credentials: dict[tuple, str] = {}
        self.exports: list[ExportResultView] = []
        self.source: tuple[MarketplaceTextContent, tuple[str, ...]] | None = None

    async def upsert_credentials(self, *, user_id, platform, ciphertext, label):
        self.credentials[(user_id, platform)] = ciphertext
        return MarketplaceCredentialView(
            platform=platform,
            is_configured=True,
            label=label,
            updated_at=datetime.now(UTC),
        )

    async def get_credentials_ciphertext(self, *, user_id, platform):
        return self.credentials.get((user_id, platform))

    async def list_credentials(self, user_id):
        return tuple(
            MarketplaceCredentialView(
                platform=platform,
                is_configured=True,
                label=None,
                updated_at=datetime.now(UTC),
            )
            for (uid, platform), _ in self.credentials.items()
            if uid == user_id
        )

    async def delete_credentials(self, *, user_id, platform):
        return self.credentials.pop((user_id, platform), None) is not None

    async def get_completed_export_source(self, *, user_id, generation_job_id):
        return self.source

    async def save_export(
        self,
        *,
        user_id,
        platform,
        generation_job_id,
        status,
        vendor_code,
        external_task_id,
        external_offer_id,
        message,
        validation_payload,
        request_payload,
    ):
        from app.domain.export import (
            CardValidationReport,
            ValidationIssue,
            ValidationSeverity,
            get_marketplace_requirements,
        )

        issues = tuple(
            ValidationIssue(
                code=item["code"],
                message=item["message"],
                severity=ValidationSeverity(item["severity"]),
                field=item.get("field"),
            )
            for item in validation_payload.get("issues", [])
        )
        result = ExportResultView(
            id=uuid4(),
            platform=platform,
            generation_job_id=generation_job_id,
            status=status,
            external_task_id=external_task_id,
            external_offer_id=external_offer_id,
            vendor_code=vendor_code,
            message=message,
            validation=CardValidationReport(
                platform=platform,
                is_valid=bool(validation_payload.get("is_valid")),
                issues=issues,
                title_length=int(validation_payload.get("title_length", 0)),
                description_length=int(validation_payload.get("description_length", 0)),
                photo_count=int(validation_payload.get("photo_count", 0)),
                requirements=get_marketplace_requirements(platform),
            ),
            created_at=datetime.now(UTC),
        )
        self.exports.append(result)
        return result


class FakeImages:
    def __init__(self, images: tuple[ImageAssetMeta, ...]) -> None:
        self.images = images

    async def inspect_images(self, object_keys):
        by_key = {image.object_key: image for image in self.images}
        return tuple(by_key[key] for key in object_keys)

    async def public_urls(self, object_keys):
        return tuple(f"https://cdn.example/{key}" for key in object_keys)


class FakeSeller:
    platform = MarketplacePlatform.WILDBERRIES

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_product_draft(self, **kwargs):
        self.calls.append(kwargs)
        return ("task-1", kwargs["vendor_code"], "queued")


@pytest.mark.asyncio
async def test_export_dry_run_persists_validated_without_seller_call() -> None:
    user_id = uuid4()
    job_id = uuid4()
    images = _portrait_images(5)
    text = MarketplaceTextContent(
        title=_valid_title(MarketplacePlatform.WILDBERRIES),
        description=_valid_description(MarketplacePlatform.WILDBERRIES),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = (text, tuple(image.object_key for image in images))
    seller = FakeSeller()
    service = ExportService(
        repo,
        FakeImages(images),
        {MarketplacePlatform.WILDBERRIES: seller},
        fernet_secret="test-secret",
    )

    result = await service.export_to_draft(
        user_id=user_id,
        generation_job_id=job_id,
        platform=MarketplacePlatform.WILDBERRIES,
        vendor_code="ART-1",
        extras={"subject_id": 105},
        dry_run=True,
    )

    assert result.status is ExportStatus.VALIDATED
    assert seller.calls == []
    assert len(repo.exports) == 1


@pytest.mark.asyncio
async def test_export_submits_after_validation_when_credentials_exist() -> None:
    user_id = uuid4()
    job_id = uuid4()
    images = _portrait_images(5)
    text = MarketplaceTextContent(
        title=_valid_title(MarketplacePlatform.WILDBERRIES),
        description=_valid_description(MarketplacePlatform.WILDBERRIES),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = (text, tuple(image.object_key for image in images))
    seller = FakeSeller()
    service = ExportService(
        repo,
        FakeImages(images),
        {MarketplacePlatform.WILDBERRIES: seller},
        fernet_secret="test-secret",
    )
    await service.save_credentials(
        user_id=user_id,
        platform=MarketplacePlatform.WILDBERRIES,
        credentials={"api_token": "wb-secret"},
    )

    result = await service.export_to_draft(
        user_id=user_id,
        generation_job_id=job_id,
        platform=MarketplacePlatform.WILDBERRIES,
        vendor_code="ART-2",
        extras={"subject_id": 105},
    )

    assert result.status is ExportStatus.SUBMITTED
    assert result.external_task_id == "task-1"
    assert len(seller.calls) == 1
    assert seller.calls[0]["image_urls"][0].startswith("https://cdn.example/")


@pytest.mark.asyncio
async def test_export_requires_credentials_when_not_dry_run() -> None:
    user_id = uuid4()
    job_id = uuid4()
    images = _portrait_images(5)
    text = MarketplaceTextContent(
        title=_valid_title(MarketplacePlatform.WILDBERRIES),
        description=_valid_description(MarketplacePlatform.WILDBERRIES),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = (text, tuple(image.object_key for image in images))
    service = ExportService(
        repo,
        FakeImages(images),
        {MarketplacePlatform.WILDBERRIES: FakeSeller()},
        fernet_secret="test-secret",
    )

    with pytest.raises(ExportNotFoundError):
        await service.export_to_draft(
            user_id=user_id,
            generation_job_id=job_id,
            platform=MarketplacePlatform.WILDBERRIES,
            vendor_code="ART-3",
            extras={"subject_id": 105},
        )


@pytest.mark.asyncio
async def test_export_blocks_when_validation_fails() -> None:
    user_id = uuid4()
    job_id = uuid4()
    bad_images = (
        ImageAssetMeta(
            object_key="bad.jpg",
            width=100,
            height=100,
            size_bytes=1000,
            format="JPEG",
        ),
    )
    text = MarketplaceTextContent(
        title=_valid_title(MarketplacePlatform.WILDBERRIES),
        description=_valid_description(MarketplacePlatform.WILDBERRIES),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = (text, ("bad.jpg",))
    service = ExportService(
        repo,
        FakeImages(bad_images),
        {MarketplacePlatform.WILDBERRIES: FakeSeller()},
        fernet_secret="test-secret",
    )

    with pytest.raises(ExportValidationError) as exc_info:
        await service.export_to_draft(
            user_id=user_id,
            generation_job_id=job_id,
            platform=MarketplacePlatform.WILDBERRIES,
            vendor_code="ART-4",
            dry_run=True,
        )
    assert not exc_info.value.report.is_valid
