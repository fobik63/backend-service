"""API endpoints for generated marketplace text content."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.schemas.generations import MarketplaceTextResponse
from app.domain.generation import MarketplaceTextContent
from app.infrastructure.persistence.generation_repository import GenerationRepository
from app.models.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/v1/generation-texts", tags=["generation-texts"])


@router.get("/{task_id}", response_model=MarketplaceTextResponse)
async def get_generation_marketplace_text(
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MarketplaceTextResponse:
    """Return AI-generated WB/Ozon copy for a completed generation."""

    repository = GenerationRepository(db_session)
    job = await repository.get_job_for_user(task_id, current_user.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation task was not found.",
        )
    if not job.marketplace_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Marketplace text is not ready for this generation.",
        )
    content = MarketplaceTextContent.model_validate(job.marketplace_text)
    return MarketplaceTextResponse.from_domain(content)
