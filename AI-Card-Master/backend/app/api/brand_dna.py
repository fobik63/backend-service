"""BrandDNA API: inspect / refresh / toggle learned seller style context."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.domain.brand_dna import BrandDNAStatus, BrandDNAView
from app.infrastructure.brand_dna_factory import build_brand_dna_service
from app.infrastructure.celery_app import celery_app
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/brand-dna", tags=["brand-dna"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrandDNAResponse(StrictAPIModel):
    id: UUID
    status: BrandDNAStatus
    is_active: bool
    midjourney_context: str | None = None
    claude_context: str | None = None
    dominant_styles: tuple[str, ...] = ()
    palette_keywords: tuple[str, ...] = ()
    lighting_mood: tuple[str, ...] = ()
    composition_keywords: tuple[str, ...] = ()
    category_hints: tuple[str, ...] = ()
    sample_count: int = Field(ge=0)
    source_job_ids: tuple[UUID, ...] = ()
    version: int = Field(ge=1)
    last_analyzed_at: str | None = None
    created_at: str
    updated_at: str


class BrandDNAActiveRequest(StrictAPIModel):
    is_active: bool


class BrandDNARefreshResponse(StrictAPIModel):
    queued: bool
    user_id: UUID


def _to_response(view: BrandDNAView) -> BrandDNAResponse:
    return BrandDNAResponse(
        id=view.id,
        status=view.status,
        is_active=view.is_active,
        midjourney_context=view.midjourney_context,
        claude_context=view.claude_context,
        dominant_styles=view.dominant_styles,
        palette_keywords=view.palette_keywords,
        lighting_mood=view.lighting_mood,
        composition_keywords=view.composition_keywords,
        category_hints=view.category_hints,
        sample_count=view.sample_count,
        source_job_ids=view.source_job_ids,
        version=view.version,
        last_analyzed_at=(
            view.last_analyzed_at.isoformat() if view.last_analyzed_at else None
        ),
        created_at=view.created_at.isoformat(),
        updated_at=view.updated_at.isoformat(),
    )


@router.get("", response_model=BrandDNAResponse)
async def get_brand_dna(
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BrandDNAResponse:
    """Return the seller BrandDNA learned from successful generations."""

    view = await build_brand_dna_service(db_session).get(user_id=current_user.id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BrandDNA is not ready yet. Complete a generation first.",
        )
    return _to_response(view)


@router.post("/refresh", response_model=BrandDNARefreshResponse)
async def refresh_brand_dna(
    current_user: Annotated[User, Depends(get_current_user)],
) -> BrandDNARefreshResponse:
    """Queue BrandDNA re-analysis of the seller's successful generations."""

    celery_app.send_task(
        "brand_dna.refresh_for_user",
        kwargs={"user_id": str(current_user.id)},
    )
    logger.info("BrandDNA refresh queued user_id=%s", current_user.id)
    return BrandDNARefreshResponse(queued=True, user_id=current_user.id)


@router.post("/activate", response_model=BrandDNAResponse)
async def set_brand_dna_active(
    payload: BrandDNAActiveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BrandDNAResponse:
    """Enable or disable automatic BrandDNA injection into new prompts."""

    view = await build_brand_dna_service(db_session).set_active(
        user_id=current_user.id,
        is_active=payload.is_active,
    )
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BrandDNA profile not found.",
        )
    return _to_response(view)
