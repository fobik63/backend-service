"""Strictly typed canvas / template layer DTOs for the card editor.

Polymorphic layers use a ``layer_type`` discriminator so
``CanvasStateDTO.layers`` validates and serializes unambiguously
(Pydantic v2 tagged union).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


LayerAlignment = Literal["left", "center", "right"]
BadgeType = Literal["discount", "rating", "top_sales"]
ShapeType = Literal["rect", "circle"]
LayerType = Literal["image", "text", "badge", "shape"]


class StrictTemplateModel(BaseModel):
    """Shared strict config for template / canvas schemas."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class BaseLayerDTO(StrictTemplateModel):
    """Common transform and stacking attributes for every canvas layer."""

    id: UUID
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
            return value
        if isinstance(value, str):
            return UUID(value)
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


class SavedDesignDTO(StrictTemplateModel):
    """User-owned design project returned by list/save endpoints."""

    id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    template_id: UUID | None = None
    canvas: CanvasStateDTO
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
