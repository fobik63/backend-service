"""Application use cases for one-click marketplace draft export."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.application.ports.exports import (
    ExportPersistencePort,
    ImageAssetPort,
    MarketplaceSellerPort,
)
from app.core.credential_crypto import (
    CredentialCryptoError,
    decrypt_credentials,
    encrypt_credentials,
)
from app.domain.export import (
    CardValidationReport,
    ExportResultView,
    ExportStatus,
    MarketplaceCredentialView,
    MarketplacePlatform,
    MarketplaceRequirements,
    MarketplaceSellerError,
    get_marketplace_requirements,
    validate_card_for_marketplace,
)


class ExportError(Exception):
    """Base Direct Export workflow failure."""


class ExportValidationError(ExportError):
    """Card fails automatic marketplace limit / photo checks."""

    def __init__(self, message: str, report: CardValidationReport) -> None:
        super().__init__(message)
        self.report = report


class ExportNotFoundError(ExportError):
    """Generation job or credentials were not found."""


class ExportForbiddenError(ExportError):
    """Caller cannot export this resource."""


class ExportUpstreamError(ExportError):
    """Marketplace seller API rejected or failed the draft create call."""


class ExportService:
    """Validate generated cards and push them to WB / Ozon / Amazon drafts."""

    def __init__(
        self,
        repository: ExportPersistencePort,
        images: ImageAssetPort,
        sellers: dict[MarketplacePlatform, MarketplaceSellerPort],
        *,
        fernet_secret: str,
    ) -> None:
        if not fernet_secret.strip():
            raise ValueError("Marketplace credential encryption secret is not configured.")
        self._repository = repository
        self._images = images
        self._sellers = sellers
        self._fernet_secret = fernet_secret

    def get_requirements(self, platform: MarketplacePlatform) -> MarketplaceRequirements:
        """Return documented limits used by automatic pre-export checks."""

        return get_marketplace_requirements(platform)

    async def save_credentials(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        credentials: dict[str, str],
        label: str | None = None,
    ) -> MarketplaceCredentialView:
        """Encrypt and store per-user seller API credentials (AES-256-GCM)."""

        normalized = _normalize_credentials(platform, credentials)
        try:
            ciphertext = encrypt_credentials(normalized, secret=self._fernet_secret)
        except CredentialCryptoError as exc:
            raise ExportValidationError(str(exc), report=_empty_report(platform)) from exc
        return await self._repository.upsert_credentials(
            user_id=user_id,
            platform=platform,
            ciphertext=ciphertext,
            label=label,
        )

    async def list_credentials(self, user_id: UUID) -> tuple[MarketplaceCredentialView, ...]:
        return await self._repository.list_credentials(user_id)

    async def delete_credentials(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> None:
        deleted = await self._repository.delete_credentials(
            user_id=user_id, platform=platform
        )
        if not deleted:
            raise ExportNotFoundError(f"No {platform.value} credentials are configured.")

    async def validate_generation(
        self,
        *,
        user_id: UUID,
        generation_job_id: UUID,
        platform: MarketplacePlatform,
    ) -> CardValidationReport:
        """Run automatic character and photo checks without calling the marketplace."""

        title, description, characteristics, images = await self._load_card_assets(
            user_id=user_id,
            generation_job_id=generation_job_id,
        )
        return validate_card_for_marketplace(
            platform=platform,
            title=title,
            description=description,
            characteristics=characteristics,
            images=images,
        )

    async def export_to_draft(
        self,
        *,
        user_id: UUID,
        generation_job_id: UUID,
        platform: MarketplacePlatform,
        vendor_code: str,
        extras: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> ExportResultView:
        """
        One-click export: validate limits, then create a marketplace draft.

        dry_run=True only validates and persists a validated record (no seller API call).
        """

        code = vendor_code.strip()
        if not code or len(code) > 64:
            raise ExportValidationError(
                "vendor_code is required and must be at most 64 characters.",
                report=_empty_report(platform),
            )

        title, description, characteristics, images = await self._load_card_assets(
            user_id=user_id,
            generation_job_id=generation_job_id,
        )
        report = validate_card_for_marketplace(
            platform=platform,
            title=title,
            description=description,
            characteristics=characteristics,
            images=images,
        )
        if not report.is_valid:
            raise ExportValidationError(
                f"Card does not meet {platform.value} requirements.",
                report=report,
            )

        request_payload = {
            "vendor_code": code,
            "dry_run": dry_run,
            "extras": extras or {},
        }
        validation_payload = _report_to_dict(report)

        if dry_run:
            return await self._repository.save_export(
                user_id=user_id,
                platform=platform,
                generation_job_id=generation_job_id,
                status=ExportStatus.VALIDATED,
                vendor_code=code,
                external_task_id=None,
                external_offer_id=None,
                message="Validation passed; draft was not submitted (dry_run).",
                validation_payload=validation_payload,
                request_payload=request_payload,
            )

        credentials = await self._load_decrypted_credentials(user_id=user_id, platform=platform)
        seller = self._sellers.get(platform)
        if seller is None:
            raise ExportUpstreamError(f"No seller adapter registered for {platform.value}.")

        object_keys = tuple(image.object_key for image in images)
        image_urls = await self._images.public_urls(object_keys)
        if len(image_urls) != len(object_keys):
            raise ExportUpstreamError("Failed to build public image URLs for marketplace media.")

        try:
            task_id, offer_id, message = await seller.create_product_draft(
                credentials=credentials,
                vendor_code=code,
                title=title,
                description=description,
                characteristics=characteristics,
                image_urls=image_urls,
                extras=extras or {},
            )
        except (MarketplaceSellerError, Exception) as exc:
            await self._repository.save_export(
                user_id=user_id,
                platform=platform,
                generation_job_id=generation_job_id,
                status=ExportStatus.FAILED,
                vendor_code=code,
                external_task_id=None,
                external_offer_id=None,
                message=str(exc)[:500],
                validation_payload=validation_payload,
                request_payload=request_payload,
            )
            raise ExportUpstreamError(str(exc)) from exc

        return await self._repository.save_export(
            user_id=user_id,
            platform=platform,
            generation_job_id=generation_job_id,
            status=ExportStatus.SUBMITTED,
            vendor_code=code,
            external_task_id=task_id,
            external_offer_id=offer_id,
            message=message,
            validation_payload=validation_payload,
            request_payload=request_payload,
        )

    async def _load_card_assets(
        self,
        *,
        user_id: UUID,
        generation_job_id: UUID,
    ) -> tuple[str, str, tuple[str, ...], tuple]:
        source = await self._repository.get_completed_export_source(
            user_id=user_id,
            generation_job_id=generation_job_id,
        )
        if source is None:
            raise ExportNotFoundError(
                "Completed generation with marketplace text and photos was not found."
            )
        text, object_keys = source
        if not object_keys:
            raise ExportValidationError(
                "Generation has no completed slide images to export.",
                report=_empty_report(MarketplacePlatform.WILDBERRIES),
            )
        images = await self._images.inspect_images(object_keys)
        return text.title, text.description, text.characteristics, images

    async def _load_decrypted_credentials(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> dict[str, str]:
        ciphertext = await self._repository.get_credentials_ciphertext(
            user_id=user_id, platform=platform
        )
        if ciphertext is None:
            raise ExportNotFoundError(
                f"Connect {platform.value} API credentials before exporting."
            )
        try:
            return decrypt_credentials(ciphertext, secret=self._fernet_secret)
        except CredentialCryptoError as exc:
            raise ExportValidationError(str(exc), report=_empty_report(platform)) from exc


def _normalize_credentials(
    platform: MarketplacePlatform, credentials: dict[str, str]
) -> dict[str, str]:
    cleaned = {
        key.strip(): value.strip()
        for key, value in credentials.items()
        if key.strip() and value.strip()
    }
    required: dict[MarketplacePlatform, tuple[str, ...]] = {
        MarketplacePlatform.WILDBERRIES: ("api_token",),
        MarketplacePlatform.OZON: ("client_id", "api_key"),
        MarketplacePlatform.AMAZON: (
            "seller_id",
            "refresh_token",
            "lwa_client_id",
            "lwa_client_secret",
        ),
    }
    missing = [key for key in required[platform] if key not in cleaned]
    if missing:
        raise ExportValidationError(
            f"Missing credentials for {platform.value}: {', '.join(missing)}.",
            report=_empty_report(platform),
        )
    return cleaned


def _report_to_dict(report: CardValidationReport) -> dict[str, Any]:
    return {
        "platform": report.platform.value,
        "is_valid": report.is_valid,
        "title_length": report.title_length,
        "description_length": report.description_length,
        "photo_count": report.photo_count,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity.value,
                "field": issue.field,
            }
            for issue in report.issues
        ],
    }


def _empty_report(platform: MarketplacePlatform) -> CardValidationReport:
    requirements = get_marketplace_requirements(platform)
    return CardValidationReport(
        platform=platform,
        is_valid=False,
        issues=(),
        title_length=0,
        description_length=0,
        photo_count=0,
        requirements=requirements,
    )
