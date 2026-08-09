"""SQLAlchemy adapters for public templates and user saved designs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.templates import (
    SavedDesignView,
    TemplateDetailView,
    TemplatePageView,
    TemplateSummaryView,
)
from app.models.template import Template, UserSavedDesign


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_canvas_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _to_summary(row: Template) -> TemplateSummaryView:
    return TemplateSummaryView(
        id=row.id,
        title=row.title,
        category=row.category,
        preview_url=row.preview_url,
        downloads_count=int(row.downloads_count),
        created_at=_to_utc(row.created_at),
    )


def _to_detail(row: Template) -> TemplateDetailView:
    return TemplateDetailView(
        id=row.id,
        title=row.title,
        category=row.category,
        is_preset=bool(row.is_preset),
        author_id=row.author_id,
        canvas_data=_as_canvas_dict(row.canvas_data),
        preview_url=row.preview_url,
        downloads_count=int(row.downloads_count),
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
    )


def _to_design(row: UserSavedDesign) -> SavedDesignView:
    return SavedDesignView(
        id=row.id,
        user_id=row.user_id,
        template_id=row.template_id,
        title=row.title,
        canvas_data=_as_canvas_dict(row.canvas_data),
        editor_document_data=(
            _as_canvas_dict(row.editor_document_data)
            if row.editor_document_data is not None
            else None
        ),
        preview_url=row.preview_url,
        updated_at=_to_utc(row.updated_at),
    )


class TemplateRepository:
    """Persist public presets and per-user canvas designs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_presets(
        self,
        *,
        category: str | None,
        page: int,
        page_size: int,
    ) -> TemplatePageView:
        filters = [Template.is_preset.is_(True)]
        if category is not None and category.strip():
            filters.append(Template.category == category.strip())

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(Template).where(*filters)
            )
            or 0
        )
        offset = max(0, (page - 1) * page_size)
        result = await self._session.scalars(
            select(Template)
            .where(*filters)
            .order_by(Template.downloads_count.desc(), Template.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = tuple(_to_summary(row) for row in result.all())
        return TemplatePageView(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_preset(self, template_id: UUID) -> TemplateDetailView | None:
        row = await self._session.scalar(
            select(Template).where(
                Template.id == template_id,
                Template.is_preset.is_(True),
            )
        )
        return _to_detail(row) if row is not None else None

    async def increment_downloads(self, template_id: UUID) -> None:
        await self._session.execute(
            update(Template)
            .where(Template.id == template_id, Template.is_preset.is_(True))
            .values(downloads_count=Template.downloads_count + 1)
        )
        await self._session.commit()

    async def list_user_designs(self, *, user_id: UUID) -> tuple[SavedDesignView, ...]:
        result = await self._session.scalars(
            select(UserSavedDesign)
            .where(UserSavedDesign.user_id == user_id)
            .order_by(UserSavedDesign.updated_at.desc())
        )
        return tuple(_to_design(row) for row in result.all())

    async def get_user_design(
        self,
        *,
        design_id: UUID,
        user_id: UUID,
    ) -> SavedDesignView | None:
        row = await self._session.scalar(
            select(UserSavedDesign).where(
                UserSavedDesign.id == design_id,
                UserSavedDesign.user_id == user_id,
            )
        )
        return _to_design(row) if row is not None else None

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
        row = UserSavedDesign(
            user_id=user_id,
            title=title,
            canvas_data=canvas_data,
            editor_document_data=editor_document_data,
            template_id=template_id,
            preview_url=preview_url,
            updated_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_design(row)

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
        row = await self._session.scalar(
            select(UserSavedDesign).where(
                UserSavedDesign.id == design_id,
                UserSavedDesign.user_id == user_id,
            )
        )
        if row is None:
            return None
        row.title = title
        row.canvas_data = canvas_data
        row.editor_document_data = editor_document_data
        row.template_id = template_id
        if preview_url is not None:
            row.preview_url = preview_url
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_design(row)

    async def template_exists(self, template_id: UUID) -> bool:
        value = await self._session.scalar(
            select(Template.id).where(Template.id == template_id)
        )
        return value is not None

    async def delete_design(self, *, design_id: UUID, user_id: UUID) -> bool:
        result = await self._session.execute(
            delete(UserSavedDesign).where(
                UserSavedDesign.id == design_id,
                UserSavedDesign.user_id == user_id,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)
