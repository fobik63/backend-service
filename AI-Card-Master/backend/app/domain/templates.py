"""Template and saved-design domain views (persistence-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TemplateSummaryView:
    """Public catalog card for a ready-made preset."""

    id: UUID
    title: str
    category: str
    preview_url: str | None
    downloads_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TemplateDetailView:
    """Full public template including Fabric-compatible canvas JSON."""

    id: UUID
    title: str
    category: str
    is_preset: bool
    author_id: UUID | None
    canvas_data: dict[str, Any]
    preview_url: str | None
    downloads_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TemplatePageView:
    """Paginated preset catalog page."""

    items: tuple[TemplateSummaryView, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class SavedDesignView:
    """User-owned canvas project (autosave / bookmark)."""

    id: UUID
    user_id: UUID
    template_id: UUID | None
    title: str
    canvas_data: dict[str, Any]
    editor_document_data: dict[str, Any] | None
    preview_url: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DesignRenderResult:
    """Outcome of a high-resolution design export uploaded to object storage."""

    design_id: UUID
    object_key: str
    presigned_url: str
    width: int
    height: int
    mime_type: str
    size_bytes: int
    expires_in_seconds: int
