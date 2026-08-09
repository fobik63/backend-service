"""Strictly typed canvas / template layer DTOs for the card editor.

Polymorphic layers use a ``layer_type`` discriminator so
``CanvasStateDTO.layers`` validates and serializes unambiguously
(Pydantic v2 tagged union).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LayerAlignment = Literal["left", "center", "right"]
BadgeType = Literal["discount", "rating", "top_sales"]
ShapeType = Literal["rect", "circle"]
LayerType = Literal["image", "text", "badge", "shape"]


class StrictTemplateModel(BaseModel):
    """Shared strict config for template / canvas schemas."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class BaseLayerDTO(StrictTemplateModel):
    """Common transform and stacking attributes for every canvas layer."""

    id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    visible: bool = True
    locked: bool = False
    x: float
    y: float
    width: float = Field(..., gt=0.0)
    height: float = Field(..., gt=0.0)
    rotation: float = Field(
        default=0.0,
        description="Rotation in degrees (clockwise positive).",
    )
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = 0

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_layer_id(cls, value: object) -> object:
        """Accept JSON UUID strings while keeping ``strict`` for other fields."""

        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return value


class ImageLayerDTO(BaseLayerDTO):
    """Raster / product image layer with optional crop window."""

    layer_type: Literal["image"] = "image"
    url: str = Field(..., min_length=1, max_length=2048)
    scale_x: float = Field(default=1.0, gt=0.0)
    scale_y: float = Field(default=1.0, gt=0.0)
    crop_x: float | None = Field(default=None, ge=0.0)
    crop_y: float | None = Field(default=None, ge=0.0)
    crop_w: float | None = Field(default=None, gt=0.0)
    crop_h: float | None = Field(default=None, gt=0.0)


class TextLayerDTO(BaseLayerDTO):
    """Typography layer for titles, offers, and body copy."""

    layer_type: Literal["text"] = "text"
    text: str = Field(..., min_length=0, max_length=8000)
    font_family: str = Field(..., min_length=1, max_length=128)
    font_size: int = Field(..., ge=1, le=512)
    font_weight: str = Field(..., min_length=1, max_length=64)
    color_hex: str = Field(
        ...,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    alignment: LayerAlignment = "left"
    line_height: float = Field(default=1.2, gt=0.0)
    letter_spacing: float = 0.0
    shadow_color: str | None = Field(
        default=None,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    shadow_blur: float = Field(default=0.0, ge=0.0)


class BadgeLayerDTO(BaseLayerDTO):
    """Marketplace badge / sticker layer (discount, rating, top sales)."""

    layer_type: Literal["badge"] = "badge"
    badge_type: BadgeType
    text: str = Field(..., min_length=1, max_length=256)
    bg_color: str = Field(
        ...,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    text_color: str = Field(
        ...,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )


class ShapeLayerDTO(BaseLayerDTO):
    """Primitive shape layer (rectangle or circle)."""

    layer_type: Literal["shape"] = "shape"
    shape_type: ShapeType
    fill_color: str = Field(
        ...,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    stroke_color: str | None = Field(
        default=None,
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    stroke_width: float = Field(default=0.0, ge=0.0)


CanvasLayerDTO = Annotated[
    ImageLayerDTO | TextLayerDTO | BadgeLayerDTO | ShapeLayerDTO,
    Field(discriminator="layer_type"),
]


class CanvasStateDTO(StrictTemplateModel):
    """Root canvas document: dimensions, background, and ordered layers."""

    width: int = Field(default=1080, ge=1, le=8192)
    height: int = Field(default=1440, ge=1, le=8192)
    background_color: str = Field(
        default="#FFFFFF",
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    background_image_url: str | None = Field(default=None, min_length=1, max_length=2048)
    layers: list[CanvasLayerDTO] = Field(default_factory=list)


class EditorSoftboxDTO(StrictTemplateModel):
    """Editor lighting state persisted with a multi-page project."""

    enabled: bool = True
    light_angle: float = Field(default=45.0, ge=0.0, le=360.0)
    light_elevation: float = Field(default=55.0, ge=10.0, le=90.0)
    color_temp_k: int = Field(default=5500, ge=2700, le=6500)
    intensity: float = Field(default=100.0, ge=0.0, le=200.0)
    softbox_diffusion: float = Field(default=65.0, ge=0.0, le=100.0)


class EditorTextStyleDTO(StrictTemplateModel):
    font_family: Literal["Inter", "Montserrat", "Roboto", "Space Grotesk"]
    font_size: int = Field(..., ge=1, le=512)
    font_weight: int = Field(..., ge=100, le=900)
    color: str = Field(..., min_length=1, max_length=64)
    stroke_width: float = Field(default=0.0, ge=0.0, le=32.0)
    stroke_color: str = Field(default="#000000", min_length=1, max_length=64)
    shadow_enabled: bool = False
    shadow_color: str = Field(default="#00000066", min_length=1, max_length=64)
    shadow_blur: float = Field(default=0.0, ge=0.0, le=128.0)
    shadow_offset_x: float = Field(default=0.0, ge=-256.0, le=256.0)
    shadow_offset_y: float = Field(default=0.0, ge=-256.0, le=256.0)


class EditorChipDTO(StrictTemplateModel):
    label: str = Field(..., min_length=1, max_length=256)
    subtitle: str | None = Field(default=None, max_length=256)
    bg_color: str = Field(..., min_length=1, max_length=128)
    border_radius: float = Field(default=14.0, ge=0.0, le=256.0)
    icon_id: str = Field(..., min_length=1, max_length=128)
    variant: Literal["solid", "glass"] = "solid"
    text_color: str | None = Field(default=None, min_length=1, max_length=64)
    blur: float = Field(default=0.0, ge=0.0, le=128.0)


class EditorLayerBaseDTO(StrictTemplateModel):
    id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    visible: bool = True
    locked: bool = False
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=0, ge=-10_000, le=10_000)
    x: float = Field(default=0.0, ge=-200.0, le=300.0)
    y: float = Field(default=0.0, ge=-200.0, le=300.0)
    width: float = Field(default=10.0, gt=0.0, le=500.0)
    height: float = Field(default=10.0, gt=0.0, le=500.0)
    scale: float = Field(default=1.0, gt=0.0, le=100.0)
    rotation: float = Field(default=0.0, ge=-3600.0, le=3600.0)


class EditorBackgroundLayerDTO(EditorLayerBaseDTO):
    type: Literal["background"] = "background"


class EditorImageLayerDTO(EditorLayerBaseDTO):
    type: Literal["image"] = "image"


class EditorTextLayerDTO(EditorLayerBaseDTO):
    type: Literal["text"] = "text"
    text: str = Field(default="", max_length=8000)
    text_style: EditorTextStyleDTO


class EditorShapeLayerDTO(EditorLayerBaseDTO):
    type: Literal["shape"] = "shape"
    chip: EditorChipDTO


EditorLayerDTO = Annotated[
    EditorBackgroundLayerDTO
    | EditorImageLayerDTO
    | EditorTextLayerDTO
    | EditorShapeLayerDTO,
    Field(discriminator="type"),
]


class EditorPageDTO(StrictTemplateModel):
    """One ordered page inside a card pack."""

    id: str = Field(..., min_length=1, max_length=128)
    layers: list[EditorLayerDTO] = Field(..., min_length=1, max_length=256)


class EditorDocumentDTO(StrictTemplateModel):
    """Versioned, complete editor state for all pages in a project."""

    version: Literal[1] = 1
    pages: list[EditorPageDTO] = Field(..., min_length=1, max_length=20)
    active_page_index: int = Field(default=0, ge=0, le=19)
    pack_size: int = Field(..., ge=1, le=20)
    product_preview_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
    )
    softbox: EditorSoftboxDTO = Field(default_factory=EditorSoftboxDTO)

    @model_validator(mode="after")
    def validate_page_bounds(self) -> "EditorDocumentDTO":
        if self.pack_size != len(self.pages):
            raise ValueError("pack_size must equal the number of pages.")
        if self.active_page_index >= len(self.pages):
            raise ValueError("active_page_index is outside the pages array.")
        page_ids = [page.id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("Editor page ids must be unique.")
        return self


# ---------------------------------------------------------------------------
# REST API request / response contracts
# ---------------------------------------------------------------------------


class TemplateSummaryDTO(StrictTemplateModel):
    """Lightweight preset row for catalog listings."""

    id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    preview_url: str | None = None
    downloads_count: int = Field(..., ge=0)
    created_at: str


class TemplateDetailDTO(StrictTemplateModel):
    """Full preset including validated canvas document."""

    id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    is_preset: bool = True
    author_id: UUID | None = None
    canvas: CanvasStateDTO
    preview_url: str | None = None
    downloads_count: int = Field(..., ge=0)
    created_at: str
    updated_at: str


class TemplateListResponse(StrictTemplateModel):
    """Paginated public preset catalog."""

    items: list[TemplateSummaryDTO]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    has_more: bool


class SaveDesignRequest(StrictTemplateModel):
    """Create or update a user canvas project.

    When ``id`` is set, the design is updated (must belong to the caller).
    Otherwise a new design row is inserted.
    """

    id: UUID | None = Field(
        default=None,
        description="Existing design id for upsert; omit to create.",
    )
    title: str = Field(..., min_length=1, max_length=255)
    template_id: UUID | None = Field(
        default=None,
        description="Optional source preset this design was forked from.",
    )
    preview_url: str | None = Field(default=None, min_length=1, max_length=2048)
    canvas: CanvasStateDTO
    editor_document: EditorDocumentDTO | None = None


class SavedDesignDTO(StrictTemplateModel):
    """User-owned design project returned by list/save endpoints."""

    id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    template_id: UUID | None = None
    canvas: CanvasStateDTO
    editor_document: EditorDocumentDTO | None = None
    preview_url: str | None = None
    updated_at: str


class SavedDesignListResponse(StrictTemplateModel):
    """All projects for the authenticated user."""

    items: list[SavedDesignDTO]
    total: int = Field(..., ge=0)


class DesignRenderRequest(StrictTemplateModel):
    """Optional render overrides for HD export."""

    output_format: Literal["png", "webp"] = "png"


class DesignRenderResponse(StrictTemplateModel):
    """Presigned S3 download for a high-resolution rendered card."""

    design_id: UUID
    object_key: str = Field(..., min_length=1)
    presigned_url: str = Field(..., min_length=1)
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)
    mime_type: Literal["image/png", "image/webp"]
    size_bytes: int = Field(..., ge=1)
    expires_in_seconds: int = Field(..., ge=1)
