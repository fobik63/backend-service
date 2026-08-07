"""Composition root helpers for BrandDNA (API + Celery + generation hooks)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.brand_dna_service import BrandDNAService
from app.core.config import get_settings
from app.infrastructure.persistence.brand_dna_repository import (
    BrandDNARepository,
    SuccessfulGenerationsRepository,
)


def build_brand_dna_service(db_session: AsyncSession) -> BrandDNAService:
    """Wire BrandDNA ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    return BrandDNAService(
        BrandDNARepository(db_session),
        SuccessfulGenerationsRepository(db_session),
        sample_limit=settings.brand_dna_sample_limit,
        min_samples=settings.brand_dna_min_samples,
        enabled=settings.brand_dna_enabled,
    )
