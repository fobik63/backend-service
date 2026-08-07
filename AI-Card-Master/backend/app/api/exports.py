"""Direct Export API: credentials, Fail-Safe sandbox, and one-click drafts."""

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
from app.domain.export import (
    CardValidationReport,
    ExportResultView,
    MarketplaceCredentialView,
    MarketplacePlatform,
    MarketplaceRequirements,
    ValidationSeverity,
)
from app.domain.export_fail_safe import ExportFixSuggestion, FailSafeSandboxResult
from app.infrastructure.export_factory import build_export_service
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
    """Fail-Safe sandbox request (plan §59)."""

    generation_job_id: UUID
    platform: MarketplacePlatform
    extras: dict[str, Any] = Field(default_factory=dict)
    require_category_ids: bool = False
    suggest_fix: bool = True


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
    forbidden_hits: int = 0
    category_errors: int = 0


class ExportFixSuggestionResponse(StrictAPIModel):
    title: str
    description: str
    characteristics: list[str]
    category_hint: str = ""
    suggested_subject_id: int | None = None
    suggested_description_category_id: int | None = None
    suggested_type_id: int | None = None
    suggested_product_type: str = ""
    fix_summary: str
    removed_phrases: list[str] = Field(default_factory=list)
    model_name: str = ""
    confidence: float = 0.0


class FailSafeSandboxResponse(StrictAPIModel):
    """Fail-Safe validator-sandbox result with optional Claude auto-fix."""

    platform: MarketplacePlatform
    is_valid: bool
    title_length: int
    description_length: int
    photo_count: int
    issues: list[ValidationIssueResponse]
    forbidden_hits: int = 0
    category_errors: int = 0
    suggested_fix: ExportFixSuggestionResponse | None = None
    claude_fix_attempted: bool = False
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0


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
    """Request-scoped Direct Export + Fail-Safe use-case service."""

    return build_export_service(db_session)


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

    from app.domain.audit_log import AuditEventStatus, AuditEventType
    from app.services.audit_events import record_audit_event

    await record_audit_event(
        event_type=AuditEventType.SETTINGS_CHANGED,
        status=AuditEventStatus.SUCCESS,
        user_id=current_user.id,
        telegram_id=current_user.telegram_id,
        actor_type="user",
        message=f"Export credentials saved for {platform.value}",
        metadata={"setting": "export_credentials", "platform": platform.value},
    )
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

    from app.domain.audit_log import AuditEventStatus, AuditEventType
    from app.services.audit_events import record_audit_event

    await record_audit_event(
        event_type=AuditEventType.SETTINGS_CHANGED,
        status=AuditEventStatus.SUCCESS,
        user_id=current_user.id,
        telegram_id=current_user.telegram_id,
        actor_type="user",
        message=f"Export credentials deleted for {platform.value}",
        metadata={"setting": "export_credentials_deleted", "platform": platform.value},
    )

@router.post("/validate", response_model=FailSafeSandboxResponse)
async def validate_export_card(
    body: ValidateExportRequest,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> FailSafeSandboxResponse:
    """Fail-Safe sandbox: photo weight, forbidden words, category + Claude fix."""

    try:
        result = await service.validate_generation(
            user_id=current_user.id,
            generation_job_id=body.generation_job_id,
            platform=body.platform,
            extras=body.extras,
            require_category_ids=body.require_category_ids,
            suggest_fix=body.suggest_fix,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_export_error(exc) from exc
    return _sandbox_response(result)


@router.post("/{platform}", response_model=ExportResultResponse)
async def export_generation_to_draft(
    platform: MarketplacePlatform,
    body: ExportDraftRequest,
    current_user: User = Depends(get_current_user),
    service: ExportService = Depends(get_export_service),
) -> ExportResultResponse:
    """One-click: Fail-Safe validate, then push the card into the marketplace draft."""

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


def _validation_response(
    report: CardValidationReport,
    *,
    forbidden_hits: int = 0,
    category_errors: int = 0,
) -> ValidationReportResponse:
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
        forbidden_hits=forbidden_hits,
        category_errors=category_errors,
    )


def _fix_response(fix: ExportFixSuggestion) -> ExportFixSuggestionResponse:
    return ExportFixSuggestionResponse(
        title=fix.title,
        description=fix.description,
        characteristics=list(fix.characteristics),
        category_hint=fix.category_hint,
        suggested_subject_id=fix.suggested_subject_id,
        suggested_description_category_id=fix.suggested_description_category_id,
        suggested_type_id=fix.suggested_type_id,
        suggested_product_type=fix.suggested_product_type,
        fix_summary=fix.fix_summary,
        removed_phrases=list(fix.removed_phrases),
        model_name=fix.model_name,
        confidence=fix.confidence,
    )


def _sandbox_response(result: FailSafeSandboxResult) -> FailSafeSandboxResponse:
    report = result.sandbox.validation
    return FailSafeSandboxResponse(
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
        forbidden_hits=result.sandbox.forbidden_hits,
        category_errors=result.sandbox.category_errors,
        suggested_fix=(
            _fix_response(result.suggested_fix)
            if result.suggested_fix is not None
            else None
        ),
        claude_fix_attempted=result.claude_fix_attempted,
        claude_input_tokens=result.claude_input_tokens,
        claude_output_tokens=result.claude_output_tokens,
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
        detail: dict[str, Any] = {
            "message": str(exc),
            "validation": _validation_response(exc.report).model_dump(mode="json"),
        }
        if exc.suggested_fix is not None:
            detail["suggested_fix"] = _fix_response(exc.suggested_fix).model_dump(
                mode="json"
            )
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
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
