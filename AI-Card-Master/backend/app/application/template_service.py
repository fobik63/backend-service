"""Application use cases for public templates and user canvas designs."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.application.ports.templates import DesignRenderStoragePort, TemplatePersistencePort
from app.domain.templates import (
    DesignRenderResult,
    SavedDesignView,
    TemplateDetailView,
    TemplatePageView,
)
from app.schemas.templates import CanvasStateDTO, EditorDocumentDTO
from app.services.s3_storage import S3StorageError, S3UploadResult
from app.services.templates.renderer import (
    CanvasRenderError,
    CanvasServerRenderer,
    get_canvas_server_renderer,
)

logger = logging.getLogger(__name__)


class TemplateServiceError(Exception):
    """Base template / design workflow failure."""


class TemplateNotFoundError(TemplateServiceError):
    """Requested preset or design does not exist (or is not owned)."""


class TemplateValidationError(TemplateServiceError):
    """Invalid canvas document or save payload."""


class TemplateStorageError(TemplateServiceError):
    """Object storage failure while publishing a rendered design."""


class TemplateRenderError(TemplateServiceError):
    """Server-side canvas render failed."""


class TemplateService:
    """Coordinate preset catalog, design CRUD, and HD card export."""

    def __init__(
        self,
        repository: TemplatePersistencePort,
        *,
        storage: DesignRenderStoragePort | None = None,
        renderer: CanvasServerRenderer | None = None,
        presign_ttl_seconds: int = 3600,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._renderer = renderer or get_canvas_server_renderer()
        self._presign_ttl_seconds = max(60, int(presign_ttl_seconds))

    async def list_presets(
        self,
        *,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TemplatePageView:
        """List ready-made presets with optional category filter + pagination."""

        if page < 1:
            raise TemplateValidationError("page must be >= 1.")
        if page_size < 1 or page_size > 100:
            raise TemplateValidationError("page_size must be in 1..100.")
        normalized = category.strip() if category and category.strip() else None
        return await self._repository.list_presets(
            category=normalized,
            page=page,
            page_size=page_size,
        )

    async def get_preset(
        self,
        template_id: UUID,
        *,
        track_download: bool = False,
    ) -> TemplateDetailView:
        """Return full canvas JSON for a public preset."""

        preset = await self._repository.get_preset(template_id)
        if preset is None:
            raise TemplateNotFoundError(f"Preset {template_id} was not found.")
        if track_download:
            try:
                await self._repository.increment_downloads(template_id)
            except Exception:  # noqa: BLE001 - analytics must not break reads
                logger.warning(
                    "Failed to increment downloads for template %s",
                    template_id,
                    exc_info=True,
                )
        return preset

    async def list_designs(self, *, user_id: UUID) -> tuple[SavedDesignView, ...]:
        """List every canvas project owned by the authenticated user."""

        return await self._repository.list_user_designs(user_id=user_id)

    async def get_design(
        self,
        *,
        user_id: UUID,
        design_id: UUID,
    ) -> SavedDesignView:
        design = await self._repository.get_user_design(
            design_id=design_id,
            user_id=user_id,
        )
        if design is None:
            raise TemplateNotFoundError(
                f"Design {design_id} was not found for the current user."
            )
        return design

    async def save_design(
        self,
        *,
        user_id: UUID,
        title: str,
        canvas: CanvasStateDTO,
        editor_document: EditorDocumentDTO | None = None,
        design_id: UUID | None = None,
        template_id: UUID | None = None,
        preview_url: str | None = None,
    ) -> SavedDesignView:
        """Create or update a user design from a validated ``CanvasStateDTO``."""

        cleaned_title = title.strip()
        if not cleaned_title:
            raise TemplateValidationError("title is required.")
        if len(cleaned_title) > 255:
            raise TemplateValidationError("title must be at most 255 characters.")

        if template_id is not None:
            exists = await self._repository.template_exists(template_id)
            if not exists:
                raise TemplateValidationError(
                    f"template_id {template_id} does not exist."
                )

        canvas_data = canvas.model_dump(mode="json")
        editor_document_data = (
            editor_document.model_dump(mode="json")
            if editor_document is not None
            else None
        )

        if design_id is not None:
            updated = await self._repository.update_design(
                design_id=design_id,
                user_id=user_id,
                title=cleaned_title,
                canvas_data=canvas_data,
                editor_document_data=editor_document_data,
                template_id=template_id,
                preview_url=preview_url,
            )
            if updated is None:
                raise TemplateNotFoundError(
                    f"Design {design_id} was not found for the current user."
                )
            return updated

        return await self._repository.create_design(
            user_id=user_id,
            title=cleaned_title,
            canvas_data=canvas_data,
            editor_document_data=editor_document_data,
            template_id=template_id,
            preview_url=preview_url,
        )

    async def delete_design(self, *, user_id: UUID, design_id: UUID) -> None:
        deleted = await self._repository.delete_design(
            design_id=design_id,
            user_id=user_id,
        )
        if not deleted:
            raise TemplateNotFoundError(
                f"Design {design_id} was not found for the current user."
            )

    async def render_design(
        self,
        *,
        user_id: UUID,
        design_id: UUID,
        output_format: str = "png",
    ) -> DesignRenderResult:
        """Render a user design to a high-res card and return a Presigned S3 URL."""

        if self._storage is None:
            raise TemplateStorageError(
                "Object storage is not configured; cannot publish rendered designs."
            )

        design = await self._repository.get_user_design(
            design_id=design_id,
            user_id=user_id,
        )
        if design is None:
            raise TemplateNotFoundError(
                f"Design {design_id} was not found for the current user."
            )

        try:
            canvas = CanvasStateDTO.model_validate(design.canvas_data)
        except ValidationError as exc:
            raise TemplateValidationError(
                f"Stored canvas for design {design_id} is invalid: {exc}"
            ) from exc

        fmt = output_format.strip().lower()
        if fmt not in {"png", "webp"}:
            raise TemplateValidationError("output_format must be 'png' or 'webp'.")

        try:
            rendered = await self._renderer.render(canvas, output_format=fmt)  # type: ignore[arg-type]
        except CanvasRenderError as exc:
            raise TemplateRenderError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected canvas render failure for design %s", design_id)
            raise TemplateRenderError("Canvas rendering failed.") from exc

        object_key = (
            f"designs/{user_id}/{design_id}/{uuid4().hex}{rendered.extension}"
        )
        try:
            upload = await self._storage.upload_bytes(
                object_key=object_key,
                data=rendered.image_bytes,
                content_type=rendered.mime_type,
                presign=True,
                cache_control="private, max-age=3600",
            )
        except S3StorageError as exc:
            raise TemplateStorageError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("S3 upload failed for design %s", design_id)
            raise TemplateStorageError("Failed to upload rendered design.") from exc

        presigned = ""
        if isinstance(upload, S3UploadResult):
            presigned = upload.presigned_url
        else:
            presigned = str(getattr(upload, "presigned_url", "") or "")

        if not presigned:
            raise TemplateStorageError(
                "Upload succeeded but no presigned URL was returned."
            )

        return DesignRenderResult(
            design_id=design_id,
            object_key=object_key,
            presigned_url=presigned,
            width=rendered.width,
            height=rendered.height,
            mime_type=rendered.mime_type,
            size_bytes=len(rendered.image_bytes),
            expires_in_seconds=self._presign_ttl_seconds,
        )
