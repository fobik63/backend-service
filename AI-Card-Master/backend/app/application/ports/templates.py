"""Persistence and storage ports for template / design workflows."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.domain.templates import SavedDesignView, TemplateDetailView, TemplatePageView


class TemplatePersistencePort(Protocol):
    """Storage operations for public presets and user saved designs."""

    async def list_presets(
        self,
        *,
        category: str | None,
        page: int,
        page_size: int,
    ) -> TemplatePageView:
        """Return paginated ready-made presets, optionally filtered by category."""

    async def get_preset(self, template_id: UUID) -> TemplateDetailView | None:
        """Load a public preset by id (``is_preset=True`` only)."""

    async def increment_downloads(self, template_id: UUID) -> None:
        """Bump download counter for a preset (best-effort analytics)."""

    async def list_user_designs(self, *, user_id: UUID) -> tuple[SavedDesignView, ...]:
        """List all canvas projects owned by the user (newest first)."""

    async def get_user_design(
        self,
        *,
        design_id: UUID,
        user_id: UUID,
    ) -> SavedDesignView | None:
        """Load one design scoped to the owning user."""

    async def create_design(
        self,
        *,
        user_id: UUID,
        title: str,
        canvas_data: dict[str, Any],
        editor_document_data: dict[str, Any] | None,
        template_id: UUID | None,
        preview_url: str | None,
    ) -> SavedDesignView:
        """Insert a new user design row."""

    async def update_design(
        self,
        *,
        design_id: UUID,
        user_id: UUID,
        title: str,
        canvas_data: dict[str, Any],
        editor_document_data: dict[str, Any] | None,
        template_id: UUID | None,
        preview_url: str | None,
    ) -> SavedDesignView | None:
        """Update an existing design owned by the user; None if missing."""

    async def template_exists(self, template_id: UUID) -> bool:
        """Whether a templates row exists (preset or user template)."""

    async def delete_design(self, *, design_id: UUID, user_id: UUID) -> bool:
        """Delete an owned design and return whether a row was removed."""


class DesignRenderStoragePort(Protocol):
    """Object storage used to publish rendered design PNGs."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> Any:
        """Upload bytes and optionally return a result with ``presigned_url``."""
