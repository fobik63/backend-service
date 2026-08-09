"""Workspace API: Pro team membership and shared generation images."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.workspace_service import (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)
from app.core.config import get_settings
from app.domain.workspace import WorkspaceRole
from app.infrastructure.persistence.workspace_repository import WorkspaceRepository
from app.models.database import get_db_session
from app.models.user import User
from app.services.s3_storage import S3StorageError, get_s3_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class StrictAPIModel(BaseModel):
    """Strict API contract (forbid unknown fields)."""

    model_config = ConfigDict(extra="forbid", strict=True)


class CreateWorkspaceRequest(StrictAPIModel):
    """Optional display name when creating a Pro workspace."""

    name: str | None = Field(default=None, max_length=120)


class AddManagerRequest(StrictAPIModel):
    """Invite a manager by email or user id (exactly one required)."""

    manager_email: str | None = Field(default=None, max_length=320)
    manager_user_id: UUID | None = None

    @field_validator("manager_email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("manager_email must be a valid email address.")
        return normalized

    @model_validator(mode="after")
    def require_one_identifier(self) -> "AddManagerRequest":
        if self.manager_email is None and self.manager_user_id is None:
            raise ValueError("manager_email or manager_user_id is required.")
        if self.manager_email is not None and self.manager_user_id is not None:
            raise ValueError("Provide either manager_email or manager_user_id, not both.")
        return self


class ShareGenerationRequest(StrictAPIModel):
    """Share one of the caller's generation jobs with the team."""

    generation_job_id: UUID


class WorkspaceMemberResponse(StrictAPIModel):
    user_id: UUID
    email: str
    role: WorkspaceRole
    joined_at: str


class WorkspaceResponse(StrictAPIModel):
    id: UUID
    owner_user_id: UUID
    name: str
    max_managers: int
    manager_count: int
    members: list[WorkspaceMemberResponse]
    created_at: str


class SharedGenerationResponse(StrictAPIModel):
    share_id: UUID
    workspace_id: UUID
    generation_job_id: UUID
    shared_by_user_id: UUID
    shared_by_email: str
    status: str
    product_category: str | None = None
    thumbnail_url: str | None = None
    thumbnail_mime_type: str | None = None
    archive_url: str | None = None
    slide_result_urls: list[str]
    shared_at: str
    job_created_at: str


async def get_workspace_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> WorkspaceService:
    """Request-scoped workspace use case service."""

    return WorkspaceService(
        WorkspaceRepository(db_session),
        max_managers=get_settings().workspace_max_managers,
    )


def _to_workspace_response(workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        owner_user_id=workspace.owner_user_id,
        name=workspace.name,
        max_managers=workspace.max_managers,
        manager_count=workspace.manager_count,
        members=[
            WorkspaceMemberResponse(
                user_id=member.user_id,
                email=member.email,
                role=member.role,
                joined_at=member.joined_at.isoformat(),
            )
            for member in workspace.members
        ],
        created_at=workspace.created_at.isoformat(),
    )


def _map_workspace_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, WorkspaceForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, WorkspaceValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Workspace request failed.",
    )


async def _presign_shared(share) -> SharedGenerationResponse:
    storage = None
    try:
        storage = get_s3_storage()
    except S3StorageError:
        logger.warning("S3 unavailable while building shared workspace images", exc_info=True)

    thumbnail_url: str | None = None
    archive_url: str | None = None
    slide_urls: list[str] = []

    if storage is not None:
        if share.thumbnail_object_key:
            try:
                thumbnail_url = await storage.generate_presigned_url(
                    object_key=share.thumbnail_object_key
                )
            except S3StorageError:
                logger.warning(
                    "Could not presign thumbnail for shared job %s",
                    share.generation_job_id,
                    exc_info=True,
                )
        if share.archive_object_key:
            try:
                archive_url = await storage.generate_presigned_url(
                    object_key=share.archive_object_key
                )
            except S3StorageError:
                logger.warning(
                    "Could not presign archive for shared job %s",
                    share.generation_job_id,
                    exc_info=True,
                )
        for object_key in share.slide_result_object_keys:
            try:
                slide_urls.append(
                    await storage.generate_presigned_url(object_key=object_key)
                )
            except S3StorageError:
                logger.warning(
                    "Could not presign slide for shared job %s",
                    share.generation_job_id,
                    exc_info=True,
                )

    return SharedGenerationResponse(
        share_id=share.share_id,
        workspace_id=share.workspace_id,
        generation_job_id=share.generation_job_id,
        shared_by_user_id=share.shared_by_user_id,
        shared_by_email=share.shared_by_email,
        status=share.status,
        product_category=share.product_category,
        thumbnail_url=thumbnail_url,
        thumbnail_mime_type=share.thumbnail_mime_type,
        archive_url=archive_url,
        slide_result_urls=slide_urls,
        shared_at=share.shared_at.isoformat(),
        job_created_at=share.job_created_at.isoformat(),
    )


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_or_get_workspace(
    payload: CreateWorkspaceRequest = Body(default_factory=CreateWorkspaceRequest),
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Create (or return) the Pro owner's workspace."""

    try:
        workspace = await workspaces.ensure_workspace(
            owner_user_id=current_user.id,
            name=payload.name,
        )
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
    return _to_workspace_response(workspace)


@router.get("/me", response_model=WorkspaceResponse)
async def get_my_workspace(
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Return the workspace the caller owns or joined as a manager."""

    try:
        workspace = await workspaces.get_my_workspace(current_user.id)
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
    return _to_workspace_response(workspace)


@router.post("/managers", response_model=WorkspaceResponse)
async def add_workspace_manager(
    payload: AddManagerRequest,
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Attach a limited-rights manager (generation only, max 3)."""

    try:
        workspace = await workspaces.add_manager(
            owner_user_id=current_user.id,
            manager_email=str(payload.manager_email) if payload.manager_email else None,
            manager_user_id=payload.manager_user_id,
        )
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
    return _to_workspace_response(workspace)


@router.delete("/managers/{manager_user_id}", response_model=WorkspaceResponse)
async def remove_workspace_manager(
    manager_user_id: UUID,
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Detach a manager from the Pro owner's workspace."""

    try:
        workspace = await workspaces.remove_manager(
            owner_user_id=current_user.id,
            manager_user_id=manager_user_id,
        )
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
    return _to_workspace_response(workspace)


@router.post(
    "/shares",
    response_model=SharedGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def share_generation_with_team(
    payload: ShareGenerationRequest,
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> SharedGenerationResponse:
    """Share a generated card with all members of the caller's workspace."""

    try:
        share = await workspaces.share_generation(
            user_id=current_user.id,
            generation_job_id=payload.generation_job_id,
        )
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
    return await _presign_shared(share)


@router.get("/shares", response_model=list[SharedGenerationResponse])
async def list_shared_generations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> list[SharedGenerationResponse]:
    """List generation images shared inside the caller's team."""

    try:
        shares = await workspaces.list_shared_generations(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc

    return [await _presign_shared(share) for share in shares]


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unshare_generation(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Remove a shared generation from the team feed."""

    try:
        await workspaces.unshare_generation(user_id=current_user.id, share_id=share_id)
    except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceValidationError) as exc:
        raise _map_workspace_error(exc) from exc
