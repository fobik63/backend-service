"""Direct Export API: credentials, validation, and one-click marketplace drafts."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.export_service import (
    ExportForbiddenError,
    ExportNotFoundError,
    ExportService,
    ExportUpstreamError,
    ExportValidationError,
)
from app.core.config import get_settings
from app.domain.export import (
    CardValidationReport,
    ExportResultView,
    MarketplaceCredentialView,
    MarketplacePlatform,
    MarketplaceRequirements,
    ValidationSeverity,
)
from app.infrastructure.marketplaces.amazon_client import AmazonSellerClient
from app.infrastructure.marketplaces.image_assets import S3ImageAssetAdapter
from app.infrastructure.marketplaces.ozon_client import OzonSellerClient
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient
from app.infrastructure.persistence.export_repository import ExportRepository
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


class StrictAPIModel(BaseModel):
    """Strict API contract (forbid unknown fields)."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SaveCredentialsRequest(StrictAPIModel):
    """Store encrypted seller API credentials for one marketplace."""

    credentials: dict[str, str] = Field(min_length=1)
    label: str | None = Field(default=None, max_length=120)

    @field_validator("credentials")
    @classmethod
    def require_non_empty_values(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {
            key.strip(): item.strip()
            for key, item in value.items()
            if key.strip() and item.strip()
        }
        if not cleaned:
            raise ValueError("credentials must contain at least one non-empty value.")
        return cleaned


class CredentialResponse(StrictAPIModel):
    platform: MarketplacePlatform
    is_configured: bool
    label: str | None = None
    updated_at: str | None = None


class ValidateExportRequest(StrictAPIModel):
    generation_job_id: UUID
    platform: MarketplacePlatform


class ExportDraftRequest(StrictAPIModel):
    """One-click export of a completed generation into a marketplace draft."""

    generation_job_id: UUID
    vendor_code: str = Field(min_length=1, max_length=64)
    extras: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False

    @field_validator("vendor_code")
    @classmethod
    def normalize_vendor_code(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("vendor_code is required.")
        return cleaned


class ValidationIssueResponse(StrictAPIModel):
    code: str
    message: str
    severity: ValidationSeverity
    field: str | None = None


class PhotoLimitsResponse(StrictAPIModel):
    min_count: int
    max_count: int
    min_width: int
    min_height: int
    max_bytes: int
    allowed_formats: list[str]
    aspect_ratio: float | None = None
    require_portrait: bool


class TextLimitsResponse(StrictAPIModel):
    title_min: int
    title_max: int
    description_min: int
    description_max: int
    characteristics_min: int
    characteristics_max: int
    characteristic_max_length: int


class RequirementsResponse(StrictAPIModel):
    platform: MarketplacePlatform
    display_name: str
    text: TextLimitsResponse
    photo: PhotoLimitsResponse
    notes: list[str]


class ValidationReportResponse(StrictAPIModel):
    platform: MarketplacePlatform
    is_valid: bool
    title_length: int
    description_length: int
    photo_count: int
    issues: list[ValidationIssueResponse]


class ExportResultResponse(StrictAPIModel):
    id: UUID
    platform: MarketplacePlatform
    generation_job_id: UUID
    status: str
    vendor_code: str
    external_task_id: str | None = None
    external_offer_id: str | None = None
    message: str
    validation: ValidationReportResponse
    created_at: str


async def get_export_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> ExportService:
    """Request-scoped Direct Export use-case service."""

    settings = get_settings()
    secret = settings.marketplace_credentials_secret.get_secret_value()
    if not secret.strip():
        secret = settings.jwt_secret_key.get_secret_value()
    return ExportService(
        ExportRepository(db_session),
        S3ImageAssetAdapter(),
        {
            MarketplacePlatform.WILDBERRIES: WildberriesSellerClient(
                base_url=settings.wildberries_content_api_base_url,
                timeout_seconds=settings.marketplace_export_timeout_seconds,
            ),
            MarketplacePlatform.OZON: OzonSellerClient(
                base_url=settings.ozon_seller_api_base_url,
                timeout_seconds=settings.marketplace_export_timeout_seconds,
            ),
            MarketplacePlatform.AMAZON: AmazonSellerClient(
                sp_api_base_url=settings.amazon_sp_api_base_url,
                timeout_seconds=settings.marketplace_export_timeout_seconds,
            ),
        },
        fernet_secret=secret,
    )


@router.get("/requirements/{platform}", response_model=RequirementsResponse)
async def get_export_requirements(
    platform: MarketplacePlatform,
    service: ExportService = Depends(get_export_service),
) -> RequirementsResponse:
    """Return automatic character and photo limits for a marketplace."""

    return _requirements_response(service.get_requirements(platform))


@router.get("/credentials", response_model=list[CredentialResponse])
async def list_export_credentials(
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> list[CredentialResponse]:
    """List connected marketplaces (secrets never leave the server)."""

    rows = await service.list_credentials(current_user.id)
    return [_credential_response(row) for row in rows]


@router.put("/credentials/{platform}", response_model=CredentialResponse)
async def save_export_credentials(
    platform: MarketplacePlatform,
    body: SaveCredentialsRequest,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> CredentialResponse:
    """Encrypt and store seller API credentials for one-click export."""

    try:
        row = await service.save_credentials(
            user_id=current_user.id,
            platform=platform,
            credentials=body.credentials,
            label=body.label,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_export_error(exc) from exc
    return _credential_response(row)


@router.delete(
    "/credentials/{platform}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_export_credentials(
    platform: MarketplacePlatform,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> None:
    try:
        await service.delete_credentials(user_id=current_user.id, platform=platform)
    except Exception as exc:  # noqa: BLE001
        raise _map_export_error(exc) from exc


@router.post("/validate", response_model=ValidationReportResponse)
async def validate_export_card(
    body: ValidateExportRequest,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> ValidationReportResponse:
    """Automatically check title/description limits and photo requirements."""

    try:
        report = await service.validate_generation(
            user_id=current_user.id,
            generation_job_id=body.generation_job_id,
            platform=body.platform,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_export_error(exc) from exc
    return _validation_response(report)


@router.post("/{platform}", response_model=ExportResultResponse)
async def export_generation_to_draft(
    platform: MarketplacePlatform,
    body: ExportDraftRequest,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> ExportResultResponse:
    """One-click: validate limits, then push the card into the marketplace draft."""

    try:
        result = await service.export_to_draft(
            user_id=current_user.id,
            generation_job_id=body.generation_job_id,
            platform=platform,
            vendor_code=body.vendor_code,
            extras=body.extras,
            dry_run=body.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_export_error(exc) from exc
    return _export_response(result)


def _credential_response(row: MarketplaceCredentialView) -> CredentialResponse:
    return CredentialResponse(
        platform=row.platform,
        is_configured=row.is_configured,
        label=row.label,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _requirements_response(req: MarketplaceRequirements) -> RequirementsResponse:
    return RequirementsResponse(
        platform=req.platform,
        display_name=req.display_name,
        text=TextLimitsResponse(
            title_min=req.text.title_min,
            title_max=req.text.title_max,
            description_min=req.text.description_min,
            description_max=req.text.description_max,
            characteristics_min=req.text.characteristics_min,
            characteristics_max=req.text.characteristics_max,
            characteristic_max_length=req.text.characteristic_max_length,
        ),
        photo=PhotoLimitsResponse(
            min_count=req.photo.min_count,
            max_count=req.photo.max_count,
            min_width=req.photo.min_width,
            min_height=req.photo.min_height,
            max_bytes=req.photo.max_bytes,
            allowed_formats=sorted(req.photo.allowed_formats),
            aspect_ratio=req.photo.aspect_ratio,
            require_portrait=req.photo.require_portrait,
        ),
        notes=list(req.notes),
    )


def _validation_response(report: CardValidationReport) -> ValidationReportResponse:
    return ValidationReportResponse(
        platform=report.platform,
        is_valid=report.is_valid,
        title_length=report.title_length,
        description_length=report.description_length,
        photo_count=report.photo_count,
        issues=[
            ValidationIssueResponse(
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                field=issue.field,
            )
            for issue in report.issues
        ],
    )


def _export_response(result: ExportResultView) -> ExportResultResponse:
    return ExportResultResponse(
        id=result.id,
        platform=result.platform,
        generation_job_id=result.generation_job_id,
        status=result.status.value,
        vendor_code=result.vendor_code,
        external_task_id=result.external_task_id,
        external_offer_id=result.external_offer_id,
        message=result.message,
        validation=_validation_response(result.validation),
        created_at=result.created_at.isoformat(),
    )


def _map_export_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExportValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": str(exc),
                "validation": _validation_response(exc.report).model_dump(mode="json"),
            },
        )
    if isinstance(exc, ExportNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ExportForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ExportUpstreamError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    logger.exception("Unexpected Direct Export failure")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Direct Export request failed.",
    )
