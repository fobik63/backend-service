"""Public legal documents: Terms of Service and Privacy Policy."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.legal.documents import (
    LegalDocumentNotFoundError,
    get_privacy_policy,
    get_terms_of_service,
)

router = APIRouter(prefix="/api/v1/legal", tags=["legal"])


class LegalDocumentResponse(BaseModel):
    """Rendered legal page payload for web / mobile clients."""

    model_config = ConfigDict(extra="forbid", strict=True)

    slug: str
    title: str
    version_date: str
    content_type: str = Field(default="text/markdown")
    content: str
    operator_name: str
    support_email: str
    privacy_email: str


@router.get("/terms", response_model=LegalDocumentResponse)
async def read_terms_of_service() -> LegalDocumentResponse:
    """Return the current Terms of Service (markdown)."""

    settings = get_settings()
    try:
        content = get_terms_of_service(settings=settings)
    except LegalDocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terms of Service document is not configured.",
        ) from exc
    return LegalDocumentResponse(
        slug="terms",
        title="Terms of Service",
        version_date=settings.legal_documents_effective_date,
        content=content,
        operator_name=settings.legal_operator_name,
        support_email=settings.support_email,
        privacy_email=settings.privacy_email,
    )


@router.get("/privacy", response_model=LegalDocumentResponse)
async def read_privacy_policy() -> LegalDocumentResponse:
    """Return the current Privacy Policy (markdown), including GDPR erasure rights."""

    settings = get_settings()
    try:
        content = get_privacy_policy(settings=settings)
    except LegalDocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Privacy Policy document is not configured.",
        ) from exc
    return LegalDocumentResponse(
        slug="privacy",
        title="Privacy Policy",
        version_date=settings.legal_documents_effective_date,
        content=content,
        operator_name=settings.legal_operator_name,
        support_email=settings.support_email,
        privacy_email=settings.privacy_email,
    )
