"""Unit tests for Fail-Safe Export sandbox (plan §59)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.export_service import ExportService, ExportValidationError
from app.domain.export import (
    ExportCardSource,
    ExportResultView,
    ImageAssetMeta,
    MarketplaceCredentialView,
    MarketplacePlatform,
)
from app.domain.export_fail_safe import (
    ExportFixSuggestion,
    normalize_export_fix_payload,
    run_fail_safe_sandbox,
    scan_forbidden_words,
    validate_category_extras,
)
from app.domain.generation import MarketplaceTextContent
from app.domain.smart_reasoning import ReasoningTaskKind, ReasoningTier, tier_for_task


def _valid_title() -> str:
    return "Кроссовки мужские беговые летние"


def _valid_description() -> str:
    base = (
        "Продающее описание товара с ключевыми преимуществами, материалами, "
        "сценариями использования и уходом. "
    )
    return (base * 20)[:1200]


def _portrait_images(count: int = 3) -> tuple[ImageAssetMeta, ...]:
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


def test_forbidden_words_detected_in_title() -> None:
    hits = scan_forbidden_words(
        platform=MarketplacePlatform.WILDBERRIES,
        title="Кроссовки с гарантия 100% на весь сезон",
        description=_valid_description(),
        characteristics=("Лёгкие",),
    )
    assert hits
    assert all(issue.code == "FORBIDDEN_WORD" for issue in hits)


def test_category_requires_wb_subject_id() -> None:
    issues = validate_category_extras(
        platform=MarketplacePlatform.WILDBERRIES,
        extras={},
        require_category_ids=True,
    )
    assert any(issue.code == "CATEGORY_MISSING" for issue in issues)


def test_category_requires_ozon_ids() -> None:
    issues = validate_category_extras(
        platform=MarketplacePlatform.OZON,
        extras={"description_category_id": 10},
        require_category_ids=True,
    )
    codes = {issue.field for issue in issues if issue.code == "CATEGORY_MISSING"}
    assert "extras.type_id" in codes


def test_sandbox_flags_photo_weight_forbidden_and_category() -> None:
    heavy = ImageAssetMeta(
        object_key="heavy.jpg",
        width=900,
        height=1200,
        size_bytes=40 * 1024 * 1024,
        format="JPEG",
    )
    report = run_fail_safe_sandbox(
        platform=MarketplacePlatform.OZON,
        title="Товар виагра тест",
        description="Короткое",
        characteristics=("A",),
        images=(heavy,),
        extras={},
        require_category_ids=True,
    )
    codes = {issue.code for issue in report.validation.errors}
    assert "PHOTO_TOO_LARGE" in codes
    assert "FORBIDDEN_WORD" in codes
    assert "CATEGORY_MISSING" in codes
    assert report.forbidden_hits >= 1
    assert report.category_errors >= 1
    assert not report.is_valid


def test_normalize_export_fix_payload() -> None:
    suggestion = normalize_export_fix_payload(
        {
            "title": "Чистый заголовок",
            "description": "Безопасное описание без запрещённых обещаний.",
            "characteristics": ["Лёгкие", "Дышащие"],
            "category_hint": "Обувь",
            "suggested_subject_id": 105,
            "fix_summary": "Убраны гарантии 100% и подогнаны лимиты.",
            "removed_phrases": ["гарантия 100%"],
            "confidence": 0.9,
        },
        model_name="claude-opus-4-7",
    )
    assert isinstance(suggestion, ExportFixSuggestion)
    assert suggestion.suggested_subject_id == 105
    assert suggestion.model_name == "claude-opus-4-7"


def test_export_fail_safe_fix_routes_to_haiku() -> None:
    assert tier_for_task(ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX) is ReasoningTier.SIMPLE


class FakeExportRepository:
    def __init__(self) -> None:
        self.source: ExportCardSource | None = None
        self.exports: list[ExportResultView] = []
        self.credentials: dict[tuple, str] = {}

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
        return ()

    async def delete_credentials(self, *, user_id, platform):
        return False

    async def get_completed_export_source(self, *, user_id, generation_job_id):
        return self.source

    async def save_export(self, **kwargs):
        result = ExportResultView(
            id=uuid4(),
            platform=kwargs["platform"],
            generation_job_id=kwargs["generation_job_id"],
            status=kwargs["status"],
            external_task_id=kwargs["external_task_id"],
            external_offer_id=kwargs["external_offer_id"],
            vendor_code=kwargs["vendor_code"],
            message=kwargs["message"],
            validation=run_fail_safe_sandbox(
                platform=kwargs["platform"],
                title="x" * 20,
                description=_valid_description(),
                characteristics=("A",),
                images=_portrait_images(1),
                extras={"subject_id": 1},
                require_category_ids=True,
            ).validation,
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


class FakeFixSuggester:
    model_name = "claude-opus-4-7"

    def __init__(self) -> None:
        self.calls = 0

    async def suggest_export_fixes(self, **kwargs):
        self.calls += 1
        return (
            ExportFixSuggestion(
                title="Исправленный заголовок кроссовок",
                description=_valid_description(),
                characteristics=["Лёгкие", "Дышащие"],
                category_hint="Обувь",
                suggested_subject_id=105,
                fix_summary="Удалены запрещённые фразы.",
                removed_phrases=["гарантия 100%"],
                model_name=self.model_name,
                confidence=0.88,
            ),
            12,
            34,
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_validate_generation_returns_claude_fix_on_errors() -> None:
    images = _portrait_images()
    text = MarketplaceTextContent(
        title="Товар с гарантия 100% качества",
        description=_valid_description(),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = ExportCardSource(
        text=text,
        object_keys=tuple(image.object_key for image in images),
        product_category="Обувь",
    )
    fixer = FakeFixSuggester()
    service = ExportService(
        repo,
        FakeImages(images),
        {},
        fernet_secret="test-secret",
        fix_suggester=fixer,
    )

    result = await service.validate_generation(
        user_id=uuid4(),
        generation_job_id=uuid4(),
        platform=MarketplacePlatform.WILDBERRIES,
        extras={"subject_id": 105},
    )

    assert not result.is_valid
    assert result.claude_fix_attempted
    assert result.suggested_fix is not None
    assert result.suggested_fix.suggested_subject_id == 105
    assert fixer.calls == 1
    assert result.claude_input_tokens == 12


@pytest.mark.asyncio
async def test_export_attaches_suggested_fix_on_validation_error() -> None:
    images = _portrait_images()
    text = MarketplaceTextContent(
        title="Товар с гарантия 100% качества",
        description=_valid_description(),
        characteristics=("Лёгкие", "Дышащие", "Стильные"),
    )
    repo = FakeExportRepository()
    repo.source = ExportCardSource(
        text=text,
        object_keys=tuple(image.object_key for image in images),
    )
    fixer = FakeFixSuggester()
    service = ExportService(
        repo,
        FakeImages(images),
        {},
        fernet_secret="test-secret",
        fix_suggester=fixer,
    )

    with pytest.raises(ExportValidationError) as exc_info:
        await service.export_to_draft(
            user_id=uuid4(),
            generation_job_id=uuid4(),
            platform=MarketplacePlatform.WILDBERRIES,
            vendor_code="ART-FS",
            extras={"subject_id": 105},
            dry_run=True,
        )

    assert exc_info.value.suggested_fix is not None
    assert "гарантия 100%" in " ".join(
        exc_info.value.suggested_fix.removed_phrases
    ).lower() or exc_info.value.suggested_fix.fix_summary
