"""Unit tests for Studio Styles (lighting, shadow catcher, frame aspects)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.three_d.render_engine import (
    Offscreen3DRenderer,
    RenderEngineConfig,
    SoftwareRasterBackend,
    build_orbit_poses,
    load_mesh_bytes,
)
from app.services.three_d.styles import (
    ALLOWED_FRAME_ASPECTS,
    LIGHTING_PRESETS,
    LightingPresetName,
    LightRole,
    RenderSettingsDTO,
    ShadowCatcherFloorSettings,
    StudioBackgroundMode,
    build_shadow_catcher_floor,
    dimensions_match_aspect,
    get_lighting_preset,
    resolve_frame_dimensions,
    sample_shadow_catcher_shade,
    shade_surface_lambert,
)

_CUBE_OBJ = b"""# unit cube
v -1 -1 -1
v  1 -1 -1
v  1  1 -1
v -1  1 -1
v -1 -1  1
v  1 -1  1
v  1  1  1
v -1  1  1
f 1 2 3
f 1 3 4
f 5 8 7
f 5 7 6
f 1 5 6
f 1 6 2
f 2 6 7
f 2 7 3
f 3 7 8
f 3 8 4
f 4 8 5
f 4 5 1
"""


def test_lighting_presets_cover_required_looks() -> None:
    assert set(LIGHTING_PRESETS) == {
        LightingPresetName.STUDIO_SOFT,
        LightingPresetName.DRAMATIC_CONTRAST,
        LightingPresetName.CYBERPUNK,
    }
    soft = get_lighting_preset("studio_soft")
    roles = {light.role for light in soft.lights}
    assert LightRole.KEY in roles
    assert LightRole.FILL in roles
    assert LightRole.RIM in roles
    assert len(soft.lights) == 3
    key = next(light for light in soft.lights if light.role == LightRole.KEY)
    fill = next(light for light in soft.lights if light.role == LightRole.FILL)
    assert key.intensity == pytest.approx(1.2)
    assert fill.intensity == pytest.approx(0.6)

    dramatic = get_lighting_preset(LightingPresetName.DRAMATIC_CONTRAST)
    assert dramatic.ambient_intensity < soft.ambient_intensity
    assert dramatic.lights[0].intensity > soft.lights[0].intensity

    cyber = get_lighting_preset("cyberpunk")
    # Neon blue + pink present.
    colors = [light.color_rgb for light in cyber.lights]
    assert any(c[2] > c[0] and c[2] > 0.5 for c in colors)  # cyan/blue lean
    assert any(c[0] > 0.7 and c[1] < 0.4 for c in colors)  # pink/magenta lean


def test_unknown_lighting_preset_raises() -> None:
    with pytest.raises(ValueError, match="Unknown lighting preset"):
        get_lighting_preset("disco_ball")


def test_shadow_catcher_floor_under_mesh() -> None:
    floor = build_shadow_catcher_floor(mesh_min_y=-1.0, mesh_radius=1.0)
    assert floor is not None
    assert floor.y < -1.0
    assert floor.half_extent == pytest.approx(4.0)
    assert floor.triangle_count == 16 * 16 * 2
    assert all(v[1] == floor.y for v in floor.vertices)

    disabled = build_shadow_catcher_floor(
        mesh_min_y=-1.0,
        mesh_radius=1.0,
        settings=ShadowCatcherFloorSettings(enabled=False),
    )
    assert disabled is None


def test_soft_shadow_sample_darker_under_object() -> None:
    settings = ShadowCatcherFloorSettings(shadow_strength=0.8, shadow_softness=0.5)
    under = sample_shadow_catcher_shade(
        world_xz=(0.0, 0.0),
        mesh_radius=1.0,
        light_direction=(-0.4, 0.8, 0.3),
        settings=settings,
    )
    far = sample_shadow_catcher_shade(
        world_xz=(8.0, 8.0),
        mesh_radius=1.0,
        light_direction=(-0.4, 0.8, 0.3),
        settings=settings,
    )
    assert under < far
    assert far == pytest.approx(1.0)


def test_render_settings_aspect_1_1_and_3_4() -> None:
    square = RenderSettingsDTO.create("1:1", width=1080, height=1080)
    assert square.aspect_ratio == "1:1"
    assert square.width == square.height == 1080

    card = RenderSettingsDTO.for_marketplace_card()
    assert card.aspect_ratio == "3:4"
    assert card.width == 1080
    assert card.height == 1440
    assert dimensions_match_aspect(card.width, card.height, "3:4")


def test_render_settings_rejects_bad_aspect_and_mismatch() -> None:
    with pytest.raises(ValidationError):
        RenderSettingsDTO(
            aspect_ratio="16:9",  # type: ignore[arg-type]
            width=1920,
            height=1080,
        )
    with pytest.raises(ValidationError, match="must match aspect"):
        RenderSettingsDTO(
            aspect_ratio="3:4",
            width=1080,
            height=1080,
        )
    with pytest.raises(ValueError, match="does not match aspect"):
        resolve_frame_dimensions("1:1", width=800, height=600)


def test_resolve_frame_dimensions_from_long_side() -> None:
    assert resolve_frame_dimensions("1:1", long_side=1024) == (1024, 1024)
    assert resolve_frame_dimensions("3:4", long_side=1440) == (1080, 1440)
    assert ALLOWED_FRAME_ASPECTS == frozenset({"1:1", "3:4"})


def test_shade_surface_lambert_responds_to_normal() -> None:
    preset = get_lighting_preset(LightingPresetName.STUDIO_SOFT)
    lit = shade_surface_lambert((0.0, 1.0, 0.0), preset)
    dark = shade_surface_lambert((0.0, -1.0, 0.0), preset)
    assert sum(lit) > sum(dark)


def test_engine_config_from_studio_settings(tmp_path: Path) -> None:
    settings = RenderSettingsDTO.create(
        "3:4",
        long_side=1440,
        lighting_preset="cyberpunk",
        background_mode=StudioBackgroundMode.TRANSPARENT,
        background_rgb=(0, 0, 0),
    )
    cfg = RenderEngineConfig.from_studio_settings(
        settings,
        frame_count=4,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    assert cfg.width == 1080
    assert cfg.height == 1440
    assert cfg.lighting_preset is LightingPresetName.CYBERPUNK
    assert cfg.resolved_lighting().name is LightingPresetName.CYBERPUNK
    assert cfg.shadow_catcher.enabled is True


def test_software_backend_renders_with_shadow_catcher(tmp_path: Path) -> None:
    mesh = load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
    settings = RenderSettingsDTO.for_square(
        side=128,
        lighting_preset=LightingPresetName.STUDIO_SOFT,
    )
    cfg = RenderEngineConfig.from_studio_settings(
        settings,
        frame_count=2,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    backend = SoftwareRasterBackend()
    backend.setup(mesh, cfg)
    poses = build_orbit_poses(mesh.bounds, frame_count=2, width=128, height=128)
    frame = backend.render_frame(poses[0])
    assert len(frame) == 128 * 128 * 3
    backend.close()


def test_offscreen_renderer_accepts_studio_config(tmp_path: Path) -> None:
    settings = RenderSettingsDTO.for_marketplace_card(
        width=90,
        height=120,
        lighting_preset="dramatic_contrast",
    )
    cfg = RenderEngineConfig.from_studio_settings(
        settings,
        frame_count=3,
        fps=3,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    with Offscreen3DRenderer(cfg) as renderer:
        renderer.load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
        frames = list(renderer.iter_orbit_frames())
    assert len(frames) == 3
    assert all(len(f) == 90 * 120 * 3 for f in frames)
