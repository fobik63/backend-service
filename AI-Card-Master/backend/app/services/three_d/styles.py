"""Studio Styles — lighting presets, shadow-catcher floor, frame validation.

Flexible visual configuration for headless product renders (turntable video /
still frames). Kept free of GL backends so application / API layers can validate
settings before workers spin up EGL/OSMesa.
"""

from __future__ import annotations

import math
from enum import StrEnum
from fractions import Fraction
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Frame aspects (marketplace-safe)
# ---------------------------------------------------------------------------

FrameAspectRatio = Literal["1:1", "3:4"]

ALLOWED_FRAME_ASPECTS: Final[frozenset[str]] = frozenset({"1:1", "3:4"})

# width:height as reduced fractions — 1:1 square, 3:4 WB/Ozon product cards.
_ASPECT_FRACTIONS: Final[dict[str, Fraction]] = {
    "1:1": Fraction(1, 1),
    "3:4": Fraction(3, 4),
}

# Canonical long-side defaults used when only aspect is known.
DEFAULT_SQUARE_SIDE: Final[int] = 1080
DEFAULT_MARKETPLACE_WIDTH: Final[int] = 1080
DEFAULT_MARKETPLACE_HEIGHT: Final[int] = 1440

MIN_FRAME_SIDE: Final[int] = 64
MAX_FRAME_SIDE: Final[int] = 4096


class LightingPresetName(StrEnum):
    """Named three-point / stylised lighting looks."""

    STUDIO_SOFT = "studio_soft"
    DRAMATIC_CONTRAST = "dramatic_contrast"
    CYBERPUNK = "cyberpunk"


class LightRole(StrEnum):
    """Semantic role of a studio light."""

    KEY = "key"
    FILL = "fill"
    BACK = "back"
    RIM = "rim"
    ACCENT = "accent"


class StudioBackgroundMode(StrEnum):
    """Backdrop modes that interact with the shadow catcher."""

    TRANSPARENT = "transparent"
    GRADIENT = "gradient"
    SOLID = "solid"


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------


class LightSourceDTO(BaseModel):
    """One directional / positional light in mesh-local space.

    Positions are relative to a unit sphere around a centred mesh (Y-up).
    ``color_rgb`` channels are linear 0..1. ``softness`` 0 = hard, 1 = very soft.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: LightRole
    position: tuple[float, float, float]
    color_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = Field(default=1.0, ge=0.0, le=16.0)
    softness: float = Field(default=0.5, ge=0.0, le=1.0)
    positional: bool = True

    @field_validator("color_rgb")
    @classmethod
    def _validate_color(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        for channel in value:
            if channel < 0.0 or channel > 1.0:
                raise ValueError("color_rgb channels must be in [0.0, 1.0].")
        return value


class LightingPresetDTO(BaseModel):
    """Resolved lighting rig ready for a render backend."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: LightingPresetName
    lights: tuple[LightSourceDTO, ...] = Field(min_length=1)
    ambient_rgb: tuple[float, float, float] = (0.08, 0.08, 0.10)
    ambient_intensity: float = Field(default=0.22, ge=0.0, le=2.0)
    description: str = ""

    @field_validator("ambient_rgb")
    @classmethod
    def _validate_ambient(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        for channel in value:
            if channel < 0.0 or channel > 1.0:
                raise ValueError("ambient_rgb channels must be in [0.0, 1.0].")
        return value


def _light(
    role: LightRole,
    position: tuple[float, float, float],
    *,
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    intensity: float = 1.0,
    softness: float = 0.5,
) -> LightSourceDTO:
    return LightSourceDTO(
        role=role,
        position=position,
        color_rgb=color,
        intensity=intensity,
        softness=softness,
    )


# Soft Key / Fill / Rim — warm studio key, cool fill, silhouette rim.
_STUDIO_SOFT = LightingPresetDTO(
    name=LightingPresetName.STUDIO_SOFT,
    description=(
        "Three-point studio: warm Key (1.2), cool Fill (0.6), Rim silhouette."
    ),
    ambient_rgb=(0.10, 0.11, 0.14),
    ambient_intensity=0.24,
    lights=(
        _light(
            LightRole.KEY,
            (2.6, 3.4, 1.8),  # warm upper-right key
            color=(1.0, 0.94, 0.86),
            intensity=1.2,
            softness=0.72,
        ),
        _light(
            LightRole.FILL,
            (-2.8, 1.6, 1.4),  # soft cool fill from the left
            color=(0.78, 0.88, 1.0),
            intensity=0.6,
            softness=0.90,
        ),
        _light(
            LightRole.RIM,
            (0.15, 2.4, -3.2),  # back rim for silhouette / volume
            color=(1.0, 0.98, 0.95),
            intensity=0.85,
            softness=0.55,
        ),
    ),
)

# Hard side key, weak fill — deep contrast / drama.
_DRAMATIC_CONTRAST = LightingPresetDTO(
    name=LightingPresetName.DRAMATIC_CONTRAST,
    description="Contrasting side light with deep shadows.",
    ambient_rgb=(0.03, 0.03, 0.04),
    ambient_intensity=0.08,
    lights=(
        _light(
            LightRole.KEY,
            (3.6, 2.2, 0.4),
            color=(1.0, 0.96, 0.90),
            intensity=2.10,
            softness=0.20,
        ),
        _light(
            LightRole.FILL,
            (-1.8, 0.6, 1.5),
            color=(0.55, 0.62, 0.78),
            intensity=0.18,
            softness=0.55,
        ),
        _light(
            LightRole.BACK,
            (-0.5, 3.4, -2.8),
            color=(0.85, 0.88, 1.0),
            intensity=0.45,
            softness=0.35,
        ),
    ),
)

# Neon cyan / magenta two-tone cyberpunk look.
_CYBERPUNK = LightingPresetDTO(
    name=LightingPresetName.CYBERPUNK,
    description="Dual-tone neon contrast (cyan/blue + magenta/pink).",
    ambient_rgb=(0.04, 0.02, 0.08),
    ambient_intensity=0.12,
    lights=(
        _light(
            LightRole.KEY,
            (2.8, 1.6, 1.8),
            color=(0.15, 0.75, 1.0),  # neon blue / cyan
            intensity=1.80,
            softness=0.40,
        ),
        _light(
            LightRole.ACCENT,
            (-2.6, 1.2, 1.4),
            color=(1.0, 0.20, 0.65),  # neon pink / magenta
            intensity=1.55,
            softness=0.45,
        ),
        _light(
            LightRole.RIM,
            (0.0, 2.8, -2.6),
            color=(0.55, 0.20, 1.0),
            intensity=0.90,
            softness=0.50,
        ),
    ),
)

LIGHTING_PRESETS: Final[dict[LightingPresetName, LightingPresetDTO]] = {
    LightingPresetName.STUDIO_SOFT: _STUDIO_SOFT,
    LightingPresetName.DRAMATIC_CONTRAST: _DRAMATIC_CONTRAST,
    LightingPresetName.CYBERPUNK: _CYBERPUNK,
}


def get_lighting_preset(name: LightingPresetName | str) -> LightingPresetDTO:
    """Resolve a lighting preset by name (enum or string)."""

    if isinstance(name, LightingPresetName):
        return LIGHTING_PRESETS[name]
    try:
        key = LightingPresetName(str(name).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(p.value for p in LightingPresetName)
        raise ValueError(
            f"Unknown lighting preset {name!r}. Allowed: {allowed}."
        ) from exc
    return LIGHTING_PRESETS[key]


# ---------------------------------------------------------------------------
# Shadow catcher floor
# ---------------------------------------------------------------------------


class ShadowCatcherFloorSettings(BaseModel):
    """Virtual ground plane that only contributes contact / soft shadows."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = True
    # Plane half-extent multiplier relative to mesh bounding-sphere radius.
    size_scale: float = Field(default=4.0, ge=1.0, le=32.0)
    # Extra gap below mesh min-Y (centred mesh → usually slightly under bottom).
    y_offset: float = Field(default=0.02, ge=0.0, le=2.0)
    opacity: float = Field(default=0.55, ge=0.0, le=1.0)
    shadow_softness: float = Field(default=0.65, ge=0.0, le=1.0)
    shadow_strength: float = Field(default=0.72, ge=0.0, le=1.0)
    receive_shadows: bool = True
    # RGB of the catcher surface before shadow darkening (usually dark grey).
    albedo_rgb: tuple[float, float, float] = (0.04, 0.04, 0.05)

    @field_validator("albedo_rgb")
    @classmethod
    def _validate_albedo(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        for channel in value:
            if channel < 0.0 or channel > 1.0:
                raise ValueError("albedo_rgb channels must be in [0.0, 1.0].")
        return value


class ShadowCatcherFloorMesh(BaseModel):
    """Axis-aligned quad lying under the product (Y-up)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    y: float
    half_extent: float
    settings: ShadowCatcherFloorSettings

    @property
    def triangle_count(self) -> int:
        return len(self.faces)


def build_shadow_catcher_floor(
    *,
    mesh_min_y: float,
    mesh_radius: float,
    settings: ShadowCatcherFloorSettings | None = None,
    grid_subdivisions: int = 16,
) -> ShadowCatcherFloorMesh | None:
    """Build a shadow-catcher plane under a centred mesh.

    Returns ``None`` when the catcher is disabled. The plane sits just below
    ``mesh_min_y`` so soft contact shadows remain visible on transparent or
    gradient backgrounds without occluding the product.

    ``grid_subdivisions`` tessellates the plane so CPU soft-shadow sampling can
    vary across the surface (GL backends may still treat it as one actor).
    """

    cfg = settings or ShadowCatcherFloorSettings()
    if not cfg.enabled:
        return None

    radius = max(float(mesh_radius), 1e-6)
    half = radius * float(cfg.size_scale)
    y = float(mesh_min_y) - float(cfg.y_offset)
    divs = max(1, min(int(grid_subdivisions), 64))

    vertices_list: list[tuple[float, float, float]] = []
    for iz in range(divs + 1):
        z = -half + (2.0 * half) * (iz / divs)
        for ix in range(divs + 1):
            x = -half + (2.0 * half) * (ix / divs)
            vertices_list.append((x, y, z))

    faces_list: list[tuple[int, int, int]] = []
    stride = divs + 1
    for iz in range(divs):
        for ix in range(divs):
            i0 = iz * stride + ix
            i1 = i0 + 1
            i2 = i0 + stride
            i3 = i2 + 1
            # CCW when viewed from +Y.
            faces_list.append((i0, i1, i3))
            faces_list.append((i0, i3, i2))

    return ShadowCatcherFloorMesh(
        vertices=tuple(vertices_list),
        faces=tuple(faces_list),
        y=y,
        half_extent=half,
        settings=cfg,
    )


def sample_shadow_catcher_shade(
    *,
    world_xz: tuple[float, float],
    mesh_radius: float,
    light_direction: tuple[float, float, float],
    settings: ShadowCatcherFloorSettings,
) -> float:
    """Approximate soft elliptical contact-shadow factor in [0, 1] (1 = lit).

    Uses a Gaussian radial falloff so the umbra reads as a soft oval under the
    product (CPU software path). GL backends prefer real shadow maps.
    """

    if not settings.enabled or not settings.receive_shadows:
        return 1.0

    lx, ly, lz = light_direction
    length_xz = math.hypot(lx, lz)
    if length_xz < 1e-6:
        offset_x, offset_z = 0.0, 0.0
    else:
        bias = 0.15 * max(mesh_radius, 1e-6)
        offset_x = -(lx / length_xz) * bias
        offset_z = -(lz / length_xz) * bias

    dx = world_xz[0] - offset_x
    dz = world_xz[1] - offset_z
    # Elliptical metric: slightly elongated along X for a natural contact oval.
    dist = math.hypot(dx * 1.05, dz * 0.92)
    sigma = max(mesh_radius, 1e-6) * (0.55 + 0.85 * settings.shadow_softness)
    # Gaussian: e^(-d² / 2σ²)
    falloff = math.exp(-(dist * dist) / max(2.0 * sigma * sigma, 1e-9))
    shade = 1.0 - settings.shadow_strength * falloff
    return max(0.0, min(1.0, shade))


def shade_surface_lambert(
    normal: tuple[float, float, float],
    preset: LightingPresetDTO,
) -> tuple[float, float, float]:
    """Evaluate multi-light Lambert + ambient for a unit normal (CPU path)."""

    nx, ny, nz = _normalize3(normal)
    r = preset.ambient_rgb[0] * preset.ambient_intensity
    g = preset.ambient_rgb[1] * preset.ambient_intensity
    b = preset.ambient_rgb[2] * preset.ambient_intensity

    for light in preset.lights:
        lx, ly, lz = _normalize3(light.position)
        # Soft lights bleed a little around the terminator.
        ndotl = max(0.0, nx * lx + ny * ly + nz * lz)
        wrap = light.softness * 0.35
        ndotl = max(0.0, (ndotl + wrap) / (1.0 + wrap))
        contrib = light.intensity * ndotl
        r += light.color_rgb[0] * contrib
        g += light.color_rgb[1] * contrib
        b += light.color_rgb[2] * contrib

    return (min(1.0, r), min(1.0, g), min(1.0, b))


def _normalize3(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-12:
        return (0.0, 1.0, 0.0)
    return (x / length, y / length, z / length)


# ---------------------------------------------------------------------------
# Frame / render settings DTO
# ---------------------------------------------------------------------------


def aspect_fraction(aspect_ratio: FrameAspectRatio | str) -> Fraction:
    """Return the reduced width/height fraction for a supported aspect."""

    key = str(aspect_ratio).strip()
    if key not in _ASPECT_FRACTIONS:
        allowed = ", ".join(sorted(ALLOWED_FRAME_ASPECTS))
        raise ValueError(
            f"Unsupported aspect_ratio {aspect_ratio!r}. Allowed: {allowed}."
        )
    return _ASPECT_FRACTIONS[key]


def dimensions_match_aspect(
    width: int,
    height: int,
    aspect_ratio: FrameAspectRatio | str,
) -> bool:
    """True when ``width:height`` exactly matches the declared aspect fraction."""

    if width <= 0 or height <= 0:
        return False
    return Fraction(width, height) == aspect_fraction(aspect_ratio)


def resolve_frame_dimensions(
    aspect_ratio: FrameAspectRatio | str,
    *,
    width: int | None = None,
    height: int | None = None,
    long_side: int | None = None,
) -> tuple[int, int]:
    """Derive integer ``(width, height)`` locked to a marketplace-safe aspect.

    Priority: explicit width+height (validated) → width → height → long_side →
    built-in defaults (1080² / 1080×1440).
    """

    aspect = str(aspect_ratio).strip()
    frac = aspect_fraction(aspect)

    if width is not None and height is not None:
        if not dimensions_match_aspect(width, height, aspect):
            raise ValueError(
                f"Frame {width}x{height} does not match aspect {aspect} "
                f"(expected ratio {frac.numerator}:{frac.denominator})."
            )
        _assert_side_bounds(width, height)
        return width, height

    if width is not None:
        _assert_side_bounds(width, width)
        height_out = int(round(width * frac.denominator / frac.numerator))
        _assert_side_bounds(width, height_out)
        if not dimensions_match_aspect(width, height_out, aspect):
            # Adjust height to nearest exact multiple if rounding drifted.
            height_out = width * frac.denominator // frac.numerator
        return width, height_out

    if height is not None:
        _assert_side_bounds(height, height)
        width_out = int(round(height * frac.numerator / frac.denominator))
        _assert_side_bounds(width_out, height)
        if not dimensions_match_aspect(width_out, height, aspect):
            width_out = height * frac.numerator // frac.denominator
        return width_out, height

    if long_side is not None:
        _assert_side_bounds(long_side, long_side)
        if aspect == "1:1":
            return long_side, long_side
        # 3:4 → height is the long side.
        height_out = long_side
        width_out = height_out * frac.numerator // frac.denominator
        _assert_side_bounds(width_out, height_out)
        return width_out, height_out

    if aspect == "1:1":
        return DEFAULT_SQUARE_SIDE, DEFAULT_SQUARE_SIDE
    return DEFAULT_MARKETPLACE_WIDTH, DEFAULT_MARKETPLACE_HEIGHT


def _assert_side_bounds(width: int, height: int) -> None:
    for label, value in (("width", width), ("height", height)):
        if value < MIN_FRAME_SIDE or value > MAX_FRAME_SIDE:
            raise ValueError(
                f"{label} must be in [{MIN_FRAME_SIDE}, {MAX_FRAME_SIDE}], got {value}."
            )


class RenderSettingsDTO(BaseModel):
    """Validated visual + frame settings for a studio render pass.

    Aspect is restricted to marketplace-safe ratios:

    * ``1:1`` — square social / gallery tiles
    * ``3:4`` — Wildberries / Ozon product-card portraits
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    aspect_ratio: FrameAspectRatio
    width: int = Field(ge=MIN_FRAME_SIDE, le=MAX_FRAME_SIDE)
    height: int = Field(ge=MIN_FRAME_SIDE, le=MAX_FRAME_SIDE)
    lighting_preset: LightingPresetName = LightingPresetName.STUDIO_SOFT
    shadow_catcher: ShadowCatcherFloorSettings = Field(
        default_factory=ShadowCatcherFloorSettings
    )
    background_mode: StudioBackgroundMode = StudioBackgroundMode.GRADIENT
    background_rgb: tuple[int, int, int] = (24, 28, 36)
    elevation_degrees: float = Field(default=20.0, ge=-80.0, le=80.0)
    fill_ratio: float = Field(default=0.825, ge=0.80, le=0.85)
    fov_degrees: float = Field(default=35.0, gt=5.0, lt=120.0)

    @field_validator("aspect_ratio")
    @classmethod
    def _validate_aspect_literal(cls, value: str) -> str:
        key = str(value).strip()
        if key not in ALLOWED_FRAME_ASPECTS:
            allowed = ", ".join(sorted(ALLOWED_FRAME_ASPECTS))
            raise ValueError(
                f"aspect_ratio must be one of: {allowed} "
                f"(1:1 square, 3:4 WB/Ozon cards). Got {value!r}."
            )
        return key

    @field_validator("background_rgb")
    @classmethod
    def _validate_bg(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        for channel in value:
            if channel < 0 or channel > 255:
                raise ValueError("background_rgb channels must be in [0, 255].")
        return value

    @model_validator(mode="after")
    def _validate_dimensions_match_aspect(self) -> Self:
        if not dimensions_match_aspect(self.width, self.height, self.aspect_ratio):
            frac = aspect_fraction(self.aspect_ratio)
            raise ValueError(
                f"width/height {self.width}x{self.height} must match aspect "
                f"{self.aspect_ratio} (ratio {frac.numerator}:{frac.denominator}). "
                f"Allowed aspects: 1:1 (square), 3:4 (WB/Ozon cards)."
            )
        return self

    @classmethod
    def create(
        cls,
        aspect_ratio: FrameAspectRatio | str,
        *,
        width: int | None = None,
        height: int | None = None,
        long_side: int | None = None,
        lighting_preset: LightingPresetName | str = LightingPresetName.STUDIO_SOFT,
        shadow_catcher: ShadowCatcherFloorSettings | None = None,
        background_mode: StudioBackgroundMode | str = StudioBackgroundMode.GRADIENT,
        background_rgb: tuple[int, int, int] = (24, 28, 36),
        elevation_degrees: float = 20.0,
        fill_ratio: float = 0.825,
        fov_degrees: float = 35.0,
    ) -> RenderSettingsDTO:
        """Factory that locks dimensions to a supported aspect before validation."""

        w, h = resolve_frame_dimensions(
            aspect_ratio,
            width=width,
            height=height,
            long_side=long_side,
        )
        preset = (
            lighting_preset
            if isinstance(lighting_preset, LightingPresetName)
            else LightingPresetName(str(lighting_preset).strip().lower())
        )
        bg = (
            background_mode
            if isinstance(background_mode, StudioBackgroundMode)
            else StudioBackgroundMode(str(background_mode).strip().lower())
        )
        return cls(
            aspect_ratio=str(aspect_ratio).strip(),  # type: ignore[arg-type]
            width=w,
            height=h,
            lighting_preset=preset,
            shadow_catcher=shadow_catcher or ShadowCatcherFloorSettings(),
            background_mode=bg,
            background_rgb=background_rgb,
            elevation_degrees=elevation_degrees,
            fill_ratio=fill_ratio,
            fov_degrees=fov_degrees,
        )

    @classmethod
    def from_persisted(cls, payload: dict[str, object]) -> RenderSettingsDTO:
        """Rebuild from JSONB / ``model_dump(mode='json')`` (lists + str enums)."""

        data = dict(payload)
        bg = data.get("background_rgb")
        if isinstance(bg, list) and len(bg) == 3:
            data["background_rgb"] = (int(bg[0]), int(bg[1]), int(bg[2]))

        catcher_raw = data.get("shadow_catcher")
        catcher: ShadowCatcherFloorSettings | None = None
        if isinstance(catcher_raw, ShadowCatcherFloorSettings):
            catcher = catcher_raw
        elif isinstance(catcher_raw, dict):
            sc = dict(catcher_raw)
            albedo = sc.get("albedo_rgb")
            if isinstance(albedo, list) and len(albedo) == 3:
                sc["albedo_rgb"] = (
                    float(albedo[0]),
                    float(albedo[1]),
                    float(albedo[2]),
                )
            catcher = ShadowCatcherFloorSettings(
                enabled=bool(sc.get("enabled", True)),
                size_scale=float(sc.get("size_scale", 4.0)),
                y_offset=float(sc.get("y_offset", 0.02)),
                opacity=float(sc.get("opacity", 0.55)),
                shadow_softness=float(sc.get("shadow_softness", 0.65)),
                shadow_strength=float(sc.get("shadow_strength", 0.72)),
                receive_shadows=bool(sc.get("receive_shadows", True)),
                albedo_rgb=sc.get("albedo_rgb", (0.04, 0.04, 0.05)),  # type: ignore[arg-type]
            )

        return cls.create(
            str(data.get("aspect_ratio", "3:4")),
            width=int(data["width"]) if data.get("width") is not None else None,
            height=int(data["height"]) if data.get("height") is not None else None,
            lighting_preset=str(data.get("lighting_preset", LightingPresetName.STUDIO_SOFT)),
            shadow_catcher=catcher,
            background_mode=str(
                data.get("background_mode", StudioBackgroundMode.GRADIENT)
            ),
            background_rgb=data.get("background_rgb", (24, 28, 36)),  # type: ignore[arg-type]
            elevation_degrees=float(data.get("elevation_degrees", 20.0)),
            fill_ratio=float(data.get("fill_ratio", 0.825)),
            fov_degrees=float(data.get("fov_degrees", 35.0)),
        )

    @classmethod
    def for_square(
        cls,
        side: int = DEFAULT_SQUARE_SIDE,
        **kwargs: object,
    ) -> RenderSettingsDTO:
        """Convenience: ``1:1`` frame."""

        return cls.create("1:1", width=side, height=side, **kwargs)  # type: ignore[arg-type]

    @classmethod
    def for_marketplace_card(
        cls,
        *,
        width: int = DEFAULT_MARKETPLACE_WIDTH,
        height: int = DEFAULT_MARKETPLACE_HEIGHT,
        **kwargs: object,
    ) -> RenderSettingsDTO:
        """Convenience: ``3:4`` WB/Ozon card frame."""

        return cls.create("3:4", width=width, height=height, **kwargs)  # type: ignore[arg-type]

    @property
    def aspect_fraction(self) -> Fraction:
        return aspect_fraction(self.aspect_ratio)

    @property
    def lighting(self) -> LightingPresetDTO:
        return get_lighting_preset(self.lighting_preset)

    def build_shadow_catcher(
        self,
        *,
        mesh_min_y: float,
        mesh_radius: float,
    ) -> ShadowCatcherFloorMesh | None:
        """Materialise the shadow-catcher floor for the bound mesh."""

        return build_shadow_catcher_floor(
            mesh_min_y=mesh_min_y,
            mesh_radius=mesh_radius,
            settings=self.shadow_catcher,
        )


__all__ = [
    "ALLOWED_FRAME_ASPECTS",
    "DEFAULT_MARKETPLACE_HEIGHT",
    "DEFAULT_MARKETPLACE_WIDTH",
    "DEFAULT_SQUARE_SIDE",
    "LIGHTING_PRESETS",
    "LightRole",
    "LightSourceDTO",
    "LightingPresetDTO",
    "LightingPresetName",
    "MAX_FRAME_SIDE",
    "MIN_FRAME_SIDE",
    "RenderSettingsDTO",
    "ShadowCatcherFloorMesh",
    "ShadowCatcherFloorSettings",
    "StudioBackgroundMode",
    "aspect_fraction",
    "build_shadow_catcher_floor",
    "dimensions_match_aspect",
    "get_lighting_preset",
    "resolve_frame_dimensions",
    "sample_shadow_catcher_shade",
    "shade_surface_lambert",
]
