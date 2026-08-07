"""Persistence adapter for Direct Export credentials and history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.export import (
    CardValidationReport,
    ExportCardSource,
    ExportResultView,
    ExportStatus,
    MarketplaceCredentialView,
    MarketplacePlatform,
    ValidationIssue,
    ValidationSeverity,
    get_marketplace_requirements,
)
from app.domain.generation import GenerationJobStatus, MarketplaceTextContent, SlideStatus
from app.models.generation_job import GenerationJob
from app.models.marketplace_export import MarketplaceCredential, MarketplaceExport


class ExportRepository:
    """SQLAlchemy implementation of ExportPersistencePort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_credentials(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        ciphertext: str,
        label: str | None,
    ) -> MarketplaceCredentialView:
        row = await self._session.scalar(
            select(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform == platform.value,
            )
        )
        now = datetime.now(UTC)
        if row is None:
            row = MarketplaceCredential(
                user_id=user_id,
                platform=platform.value,
                ciphertext=ciphertext,
                label=label,
            )
            self._session.add(row)
        else:
            row.ciphertext = ciphertext
            row.label = label
            row.updated_at = now
        await self._session.commit()
        await self._session.refresh(row)
        return MarketplaceCredentialView(
            platform=platform,
            is_configured=True,
            label=row.label,
            updated_at=row.updated_at,
        )

    async def get_credentials_ciphertext(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> str | None:
        row = await self._session.scalar(
            select(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform == platform.value,
            )
        )
        return None if row is None else row.ciphertext

    async def get_credentials_ciphertext_batch(
        self,
        *,
        user_id: UUID,
        platforms: tuple[MarketplacePlatform, ...],
    ) -> dict[MarketplacePlatform, str]:
        if not platforms:
            return {}
        platform_values = tuple(platform.value for platform in platforms)
        rows = await self._session.scalars(
            select(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform.in_(platform_values),
            )
        )
        allowed = {platform.value: platform for platform in platforms}
        result: dict[MarketplacePlatform, str] = {}
        for row in rows.all():
            mapped = allowed.get(row.platform)
            if mapped is not None:
                result[mapped] = row.ciphertext
        return result

    async def list_credentials(self, user_id: UUID) -> tuple[MarketplaceCredentialView, ...]:
        rows = await self._session.scalars(
            select(MarketplaceCredential)
            .where(MarketplaceCredential.user_id == user_id)
            .order_by(MarketplaceCredential.platform.asc())
        )
        return tuple(
            MarketplaceCredentialView(
                platform=MarketplacePlatform(row.platform),
                is_configured=True,
                label=row.label,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def delete_credentials(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> bool:
        row = await self._session.scalar(
            select(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform == platform.value,
            )
        )
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True

    async def get_completed_export_source(
        self, *, user_id: UUID, generation_job_id: UUID
    ) -> ExportCardSource | None:
        job = await self._session.scalar(
            select(GenerationJob)
            .where(
                GenerationJob.id == generation_job_id,
                GenerationJob.user_id == user_id,
            )
            .options(selectinload(GenerationJob.slides))
        )
        if job is None:
            return None
        if job.status != GenerationJobStatus.COMPLETED.value:
            return None
        if not job.marketplace_text:
            return None
        text = MarketplaceTextContent.model_validate(job.marketplace_text)
        keys = tuple(
            slide.result_object_key
            for slide in sorted(job.slides, key=lambda item: item.position)
            if slide.status == SlideStatus.COMPLETED.value and slide.result_object_key
        )
        if not keys:
            return None
        category = (job.product_category or "").strip() or None
        return ExportCardSource(
            text=text,
            object_keys=keys,
            product_category=category,
        )

    async def save_export(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        generation_job_id: UUID,
        status: ExportStatus,
        vendor_code: str,
        external_task_id: str | None,
        external_offer_id: str | None,
        message: str,
        validation_payload: dict[str, Any],
        request_payload: dict[str, Any],
    ) -> ExportResultView:
        row = MarketplaceExport(
            user_id=user_id,
            generation_job_id=generation_job_id,
            platform=platform.value,
            status=status.value,
            vendor_code=vendor_code,
            external_task_id=external_task_id,
            external_offer_id=external_offer_id,
            message=message[:500],
            validation_payload=validation_payload,
            request_payload=request_payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return ExportResultView(
            id=row.id,
            platform=platform,
            generation_job_id=generation_job_id,
            status=status,
            external_task_id=external_task_id,
            external_offer_id=external_offer_id,
            vendor_code=vendor_code,
            message=row.message,
            validation=_payload_to_report(validation_payload, platform),
            created_at=row.created_at,
        )


def _payload_to_report(
    payload: dict[str, Any], platform: MarketplacePlatform
) -> CardValidationReport:
    requirements = get_marketplace_requirements(platform)
    issues = tuple(
        ValidationIssue(
            code=str(item.get("code", "UNKNOWN")),
            message=str(item.get("message", "")),
            severity=ValidationSeverity(str(item.get("severity", "error"))),
            field=item.get("field"),
        )
        for item in payload.get("issues", [])
        if isinstance(item, dict)
    )
    return CardValidationReport(
        platform=platform,
        is_valid=bool(payload.get("is_valid", False)),
        issues=issues,
        title_length=int(payload.get("title_length", 0)),
        description_length=int(payload.get("description_length", 0)),
        photo_count=int(payload.get("photo_count", 0)),
        requirements=requirements,
    )
