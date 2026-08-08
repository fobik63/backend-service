"""ModernGL offscreen mesh renderer with Lambert lighting + shadow plane.

Extracted from the orbital render engine so the GLSL shading path can evolve
independently of PyVista / software backends. Quality target: match the CPU
Lambert + shadow-catcher look used by ``SoftwareRasterBackend``.
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Any

from app.services.three_d.errors import HeadlessGLError, RenderEngineError

logger = logging.getLogger(__name__)

RGB24_BYTES_PER_PIXEL = 3

_VERTEX_SHADER = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec3 in_n;
out vec3 v_world;
out vec3 v_n;
void main() {
    v_world = in_pos;
    v_n = in_n;
    gl_Position = mvp * vec4(in_pos, 1.0);
}
"""

# Directional Lambert + soft planar shadow attenuation (contact under mesh).
_FRAGMENT_SHADER = """
#version 330
in vec3 v_world;
in vec3 v_n;
out vec4 f_color;

uniform vec3 u_albedo;
uniform vec3 u_ambient;
uniform vec3 u_light_dir;      // direction *toward* the surface (world space)
uniform vec3 u_light_color;
uniform float u_light_intensity;
uniform float u_floor_y;
uniform float u_mesh_radius;
uniform float u_shadow_strength;
uniform float u_shadow_softness;

void main() {
    vec3 n = normalize(v_n);
    vec3 L = normalize(u_light_dir);
    // Classic Lambert diffuse (clamped N·L).
    float ndotl = max(dot(n, L), 0.0);
    vec3 diffuse = u_albedo * u_light_color * (u_light_intensity * ndotl);
    vec3 lit = u_ambient + diffuse;

    // Soft contact shadow on / near the catcher plane (Y = floor).
    float radial = length(v_world.xz);
    float height = v_world.y - u_floor_y;
    float core = max(u_mesh_radius, 1e-4) * (0.55 + 0.35 * (1.0 - u_shadow_softness));
    float penumbra = max(u_mesh_radius, 1e-4) * (1.2 + 2.5 * u_shadow_softness);
    float radial_t = 1.0 - smoothstep(core, max(penumbra, core + 1e-4), radial);
    float height_t = 1.0 - smoothstep(0.0, max(u_mesh_radius * 0.18, 1e-4), abs(height));
    float shadow = mix(1.0, 1.0 - u_shadow_strength, clamp(radial_t * height_t, 0.0, 1.0));

    // Gentle hemisphere occlusion so undersides read darker (studio fill).
    float hemi = mix(1.0 - 0.35 * u_shadow_strength, 1.0, clamp(0.5 + 0.5 * n.y, 0.0, 1.0));
    vec3 color = lit * shadow * hemi;
    f_color = vec4(clamp(color, 0.0, 1.0), 1.0);
}
"""

_FLOOR_FRAGMENT_SHADER = """
#version 330
in vec3 v_world;
in vec3 v_n;
out vec4 f_color;

uniform vec3 u_bg;
uniform float u_floor_y;
uniform float u_mesh_radius;
uniform float u_shadow_strength;
uniform float u_shadow_softness;
uniform float u_opacity;

void main() {
    float radial = length(v_world.xz);
    float core = max(u_mesh_radius, 1e-4) * (0.55 + 0.35 * (1.0 - u_shadow_softness));
    float penumbra = max(u_mesh_radius, 1e-4) * (1.2 + 2.5 * u_shadow_softness);
    float t;
    if (radial <= core) {
        t = 0.0;
    } else if (radial >= penumbra) {
        t = 1.0;
    } else {
        float x = (radial - core) / max(penumbra - core, 1e-4);
        t = x * x * (3.0 - 2.0 * x);
    }
    float shade = mix(1.0 - u_shadow_strength, 1.0, t);
    vec3 albedo = vec3(0.92, 0.92, 0.94) * shade;
    vec3 color = mix(u_bg, albedo, clamp(u_opacity, 0.0, 1.0));
    f_color = vec4(color, 1.0);
}
"""


class ModernglOffscreenBackend:
    """Optional moderngl FBO path (EGL/OSMesa via ``PYOPENGL_PLATFORM``)."""

    name = "moderngl"

    def __init__(self) -> None:
        self._ctx: Any = None
        self._fbo: Any = None
        self._vao: Any = None
        self._floor_vao: Any = None
        self._prog: Any = None
        self._floor_prog: Any = None
        self._config: Any = None
        self._mesh_radius: float = 1.0
        self._floor_y: float = -0.5

    def setup(self, mesh: Any, config: Any) -> None:
        try:
            import moderngl
            import numpy as np
        except ImportError as exc:
            raise HeadlessGLError(
                "moderngl/numpy are required for this backend."
            ) from exc

        from app.services.three_d.render_engine import configure_headless_opengl
        from app.services.three_d.styles import build_shadow_catcher_floor

        configure_headless_opengl()
        ctx = moderngl.create_context(standalone=True, require=330)
        prog = ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)
        floor_prog = ctx.program(
            vertex_shader=_VERTEX_SHADER,
            fragment_shader=_FLOOR_FRAGMENT_SHADER,
        )

        verts = mesh.centered_vertices
        # Prefer precomputed smooth normals; fall back to area-weighted CPU path.
        if mesh.normals is not None and len(mesh.normals) == len(verts):
            normals = list(mesh.normals)
        else:
            accum = [[0.0, 0.0, 0.0] for _ in verts]
            for a, b, c in mesh.faces:
                n = _triangle_normal(verts[a], verts[b], verts[c])
                for idx in (a, b, c):
                    accum[idx][0] += n[0]
                    accum[idx][1] += n[1]
                    accum[idx][2] += n[2]
            normals = [_normalize((x, y, z)) for x, y, z in accum]

        interleaved: list[float] = []
        indices: list[int] = []
        for v, n in zip(verts, normals):
            interleaved.extend((v[0], v[1], v[2], n[0], n[1], n[2]))
        for a, b, c in mesh.faces:
            indices.extend((a, b, c))

        vbo = ctx.buffer(np.asarray(interleaved, dtype="f4").tobytes())
        ibo = ctx.buffer(np.asarray(indices, dtype="i4").tobytes())
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 3f", "in_pos", "in_n")],
            index_buffer=ibo,
        )

        centered_min_y = -0.5 * mesh.bounds.extents[1]
        floor = build_shadow_catcher_floor(
            mesh_min_y=centered_min_y,
            mesh_radius=mesh.bounds.radius,
            settings=config.resolved_shadow_catcher(),
        )
        floor_vao = None
        floor_y = centered_min_y
        if floor is not None:
            floor_y = floor.y
            f_interleaved: list[float] = []
            f_indices: list[int] = []
            up = (0.0, 1.0, 0.0)
            for v in floor.vertices:
                f_interleaved.extend((v[0], v[1], v[2], *up))
            for a, b, c in floor.faces:
                f_indices.extend((a, b, c))
            f_vbo = ctx.buffer(np.asarray(f_interleaved, dtype="f4").tobytes())
            f_ibo = ctx.buffer(np.asarray(f_indices, dtype="i4").tobytes())
            floor_vao = ctx.vertex_array(
                floor_prog,
                [(f_vbo, "3f 3f", "in_pos", "in_n")],
                index_buffer=f_ibo,
            )

        fbo = ctx.framebuffer(
            color_attachments=[ctx.texture((config.width, config.height), 3)],
            depth_attachment=ctx.depth_renderbuffer((config.width, config.height)),
        )

        lighting = config.resolved_lighting()
        # Prefer first key light; fall back to a classic studio key.
        if lighting.lights:
            key = lighting.lights[0]
            light_dir = _normalize(key.position)
            light_color = key.color_rgb
            light_intensity = float(key.intensity)
        else:
            light_dir = _normalize((-0.35, 0.8, 0.45))
            light_color = (1.0, 1.0, 1.0)
            light_intensity = 1.0
        ambient = tuple(
            c * lighting.ambient_intensity for c in lighting.ambient_rgb
        )
        catcher = config.resolved_shadow_catcher()

        prog["u_albedo"].value = (0.82, 0.86, 0.92)
        prog["u_ambient"].value = ambient
        prog["u_light_dir"].value = light_dir
        prog["u_light_color"].value = light_color
        prog["u_light_intensity"].value = light_intensity
        prog["u_floor_y"].value = float(floor_y)
        prog["u_mesh_radius"].value = float(mesh.bounds.radius)
        prog["u_shadow_strength"].value = float(catcher.shadow_strength)
        prog["u_shadow_softness"].value = float(catcher.shadow_softness)

        if floor_vao is not None:
            bg = config.background_rgb
            floor_prog["u_bg"].value = (bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0)
            floor_prog["u_floor_y"].value = float(floor_y)
            floor_prog["u_mesh_radius"].value = float(mesh.bounds.radius)
            floor_prog["u_shadow_strength"].value = float(catcher.shadow_strength)
            floor_prog["u_shadow_softness"].value = float(catcher.shadow_softness)
            floor_prog["u_opacity"].value = float(catcher.opacity)

        self._ctx = ctx
        self._fbo = fbo
        self._vao = vao
        self._floor_vao = floor_vao
        self._prog = prog
        self._floor_prog = floor_prog
        self._config = config
        self._mesh_radius = float(mesh.bounds.radius)
        self._floor_y = float(floor_y)

    def render_frame(self, pose: Any) -> bytes:
        if (
            not self._ctx
            or not self._fbo
            or not self._vao
            or not self._prog
            or not self._config
        ):
            raise RenderEngineError("moderngl backend is not initialised.")

        from app.services.three_d.render_engine import (
            _look_at_matrix,
            _matmul4,
            _perspective_matrix,
        )

        cfg = self._config
        view = _look_at_matrix(pose.eye, pose.target, pose.up)
        proj = _perspective_matrix(
            math.radians(cfg.fov_degrees),
            cfg.width / max(cfg.height, 1),
            0.01,
            pose.distance * 20.0,
        )
        mvp = _matmul4(proj, view)
        flat = [mvp[c][r] for r in range(4) for c in range(4)]
        packed = struct.pack("16f", *flat)
        self._prog["mvp"].write(packed)
        if self._floor_prog is not None:
            self._floor_prog["mvp"].write(packed)

        self._fbo.use()
        bg = cfg.background_rgb
        self._ctx.clear(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0)
        if self._floor_vao is not None:
            self._floor_vao.render()
        self._vao.render()
        raw = self._fbo.read(components=3, alignment=1)
        expected = cfg.width * cfg.height * RGB24_BYTES_PER_PIXEL
        if len(raw) != expected:
            raise RenderEngineError(
                f"Unexpected moderngl frame size {len(raw)} (expected {expected})."
            )
        # FBO origin is bottom-left — flip vertically for video top-left origin.
        w, h = cfg.width, cfg.height
        row = w * 3
        rows = [raw[i * row : (i + 1) * row] for i in range(h)]
        rows.reverse()
        return b"".join(rows)

    def close(self) -> None:
        for obj in (self._floor_vao, self._vao, self._fbo, self._ctx):
            if obj is None:
                continue
            try:
                release = getattr(obj, "release", None)
                if callable(release):
                    release()
            except Exception:  # noqa: BLE001
                logger.debug("moderngl release failed", exc_info=True)
        self._ctx = None
        self._fbo = None
        self._vao = None
        self._floor_vao = None
        self._prog = None
        self._floor_prog = None
        self._config = None
        # Drop GPU-adjacent Python buffers promptly under sustained render load.
        try:
            import gc

            gc.collect()
        except Exception:  # noqa: BLE001
            logger.debug("moderngl gc.collect failed", exc_info=True)


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-12:
        return (0.0, 1.0, 0.0)
    return (x / length, y / length, z / length)


def _triangle_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return _normalize((uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx))


__all__ = ["ModernglOffscreenBackend"]
