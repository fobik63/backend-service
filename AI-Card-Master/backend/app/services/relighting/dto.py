"""DTOs for virtual studio relighting (presets, maps, process results)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RelightingPresetName(StrEnum):
    """Named 2D studio lighting looks for product cards."""

    GOLDEN_HOUR = "golden_hour"
    CYBERPUNK_NEON = "cyberpunk_neon"
    DRAMATIC_STUDIO = "dramatic_studio"
    SOFT_COMMERCIAL = "soft_commercial"


class LightRole(StrEnum):
    KEY = "key"
    FILL = "fill"
    RIM = "rim"
    SPOT = "spot"
    ACCENT = "accent"


class RelightLightDTO(BaseModel):
    """Directional light in image-local space (X right, Y up, Z toward camera)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: LightRole
    direction: tuple[float, float, float] = Field(
        description="Unit-ish light direction toward the surface."
    )
    color_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = Field(default=1.0, ge=0.0, le=16.0)
    softness: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("color_rgb")
    @classmethod
    def _validate_color(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        for channel in value:
            if channel < 0.0 or channel > 1.0:
                raise ValueError("color_rgb channels must be in [0.0, 1.0].")
        return value


class LightingPresetDTO(BaseModel):
    """Resolved lighting preset ready for RelightingEngineService."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: RelightingPresetName
    description: str = ""
    color_temperature_k: int = Field(default=5500, ge=1000, le=12000)
    lights: tuple[RelightLightDTO, ...] = Field(min_length=1)
    ambient_rgb: tuple[float, float, float] = (0.10, 0.10, 0.12)
    ambient_intensity: float = Field(default=0.25, ge=0.0, le=2.0)
    background_rgb: tuple[int, int, int] = (245, 245, 248)
    shadow_blur_px: int = Field(default=18, ge=0, le=80)
    shadow_angle_deg: float = Field(default=35.0, ge=-90.0, le=90.0)
    shadow_opacity: float = Field(default=0.45, ge=0.0, le=1.0)
    cast_length: float = Field(default=0.35, ge=0.0, le=1.5)

    @field_validator("ambient_rgb")
    @classmethod
    def _validate_ambient(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        for channel in value:
            if channel < 0.0 or channel > 1.0:
                raise ValueError("ambient_rgb channels must be in [0.0, 1.0].")
        return value

    @field_validator("background_rgb")
    @classmethod
    def _validate_bg(
        cls, value: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        for channel in value:
            if channel < 0 or channel > 255:
                raise ValueError("background_rgb channels must be in [0, 255].")
        return value


class StudioLightDTO(BaseModel):
    """Parametric softbox light for custom virtual-studio relighting."""

    # Not strict: API clients often send ints for numeric softbox knobs.
    model_config = ConfigDict(extra="forbid", frozen=True)

    light_angle: float = Field(
        default=45.0,
        ge=0.0,
        le=360.0,
        description="Azimuth degrees: 0=right, 90=front(+Z), 180=left, 270=back.",
    )
    light_elevation: float = Field(
        default=55.0,
        ge=10.0,
        le=90.0,
        description="Elevation above horizon (10=side, 90=overhead).",
    )
    color_temp_k: int = Field(
        default=5500,
        ge=2700,
        le=7500,
        description="Softbox color temperature in Kelvin.",
    )
    intensity: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Key softbox intensity multiplier.",
    )
    softbox_diffusion: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="0=hard softbox edge, 1=fully diffused wrap.",
    )


class ShadowParamsDTO(BaseModel):
    """Contact + cast shadow controls derived from preset × intensity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    blur_px: int = Field(ge=0, le=80)
    angle_deg: float = Field(
        ge=-180.0,
        le=360.0,
        description="Cast/contact offset angle (shadow opposite to key light).",
    )
    opacity: float = Field(ge=0.0, le=1.0)
    cast_length: float = Field(ge=0.0, le=1.5)
    contact_strength: float = Field(default=0.55, ge=0.0, le=1.0)
    contact_offset_ratio: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Horizontal contact shift as fraction of product width "
        "(negative = left, opposite to a right-side key).",
    )


class DepthNormalMapsDTO(BaseModel):
    """Estimated depth / normal maps as PNG bytes (L and RGB respectively)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    depth_png: bytes = Field(min_length=1)
    normal_png: bytes = Field(min_length=1)
    mask_png: bytes = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RelightProcessResultDTO(BaseModel):
    """Final relit product card ready for storage / API response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    image_png: bytes = Field(min_length=1)
    depth_png: bytes = Field(min_length=1)
    normal_png: bytes = Field(min_length=1)
    preset_name: RelightingPresetName | None = None
    studio_light: StudioLightDTO | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    shadow_intensity: float = Field(ge=0.0, le=1.0)


class RelightingJobResultDTO(BaseModel):
    """Orchestrated result after billing + S3 upload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    result_url: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    preset_name: RelightingPresetName | None = None
    studio_light: StudioLightDTO | None = None
    coins_charged: int = Field(ge=0)
    new_balance: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_type: Literal["image/png"] = "image/png"
