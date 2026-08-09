"""Headless orbital 3D mesh → video renderer (EGL / OSMesa / software).

Low-level infrastructure module used by Celery workers to turn ``.glb`` /
``.gltf`` / ``.obj`` meshes into turntable preview videos without X11.

Design goals
------------
* Docker-safe offscreen GL (``vtkEGLRenderWindow`` → OSMesa → CPU software).
* Zero per-frame temp files — RGB24 frames stream through memory into FFmpeg
  ``stdin`` pipes.
* Dual encode (sequential): HQ H.264 MP4 first, then GIF/WebP after RAM release.
* Context-manager lifecycle that always tears down VRAM / subprocesses.
"""

from __future__ import annotations

import gc
import hashlib
import io
import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field

from app.services.three_d.errors import (
    FFmpegEncodeError,
    HeadlessGLError,
    MeshLoadError,
    RenderEngineError,
)
from app.services.three_d.styles import (
    LightingPresetDTO,
    LightingPresetName,
    RenderSettingsDTO,
    ShadowCatcherFloorSettings,
    build_shadow_catcher_floor,
    get_lighting_preset,
    shade_surface_lambert,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants / types
# ---------------------------------------------------------------------------

MeshFormat = Literal["glb", "gltf", "obj"]
PreviewFormat = Literal["gif", "webp"]
RenderBackendName = Literal["auto", "pyvista", "moderngl", "software"]
HeadlessGLBackend = Literal["egl", "osmesa", "software"]

DEFAULT_FRAME_COUNT = 120  # 5 s @ 24 fps
DEFAULT_FPS = 24
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FILL_RATIO = 0.825  # mid of 80–85 % target
DEFAULT_FOV_DEGREES = 35.0
DEFAULT_BACKGROUND_RGB = (24, 28, 36)
RGB24_BYTES_PER_PIXEL = 3

_SUPPORTED_SUFFIXES: dict[str, MeshFormat] = {
    ".glb": "glb",
    ".gltf": "gltf",
    ".obj": "obj",
}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class MeshBounds(BaseModel):
    """Axis-aligned bounding box in mesh-local coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.min_xyz[0] + self.max_xyz[0]) * 0.5,
            (self.min_xyz[1] + self.max_xyz[1]) * 0.5,
            (self.min_xyz[2] + self.max_xyz[2]) * 0.5,
        )

    @property
    def extents(self) -> tuple[float, float, float]:
        return (
            max(self.max_xyz[0] - self.min_xyz[0], 1e-9),
            max(self.max_xyz[1] - self.min_xyz[1], 1e-9),
            max(self.max_xyz[2] - self.min_xyz[2], 1e-9),
        )

    @property
    def radius(self) -> float:
        ex, ey, ez = self.extents
        return 0.5 * math.sqrt(ex * ex + ey * ey + ez * ez)


class OrbitCameraPose(BaseModel):
    """One sample on the virtual camera orbit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    frame_index: int = Field(ge=0)
    azimuth_rad: float
    elevation_rad: float
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    distance: float = Field(gt=0.0)


class RenderEngineConfig(BaseModel):
    """Tunables for a single offscreen render session."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    width: int = Field(default=DEFAULT_WIDTH, ge=64, le=4096)
    height: int = Field(default=DEFAULT_HEIGHT, ge=64, le=4096)
    fps: int = Field(default=DEFAULT_FPS, ge=1, le=120)
    frame_count: int = Field(default=DEFAULT_FRAME_COUNT, ge=2, le=3600)
    fill_ratio: float = Field(default=DEFAULT_FILL_RATIO, ge=0.80, le=0.85)
    fov_degrees: float = Field(default=DEFAULT_FOV_DEGREES, gt=5.0, lt=120.0)
    elevation_degrees: float = Field(default=20.0, ge=-80.0, le=80.0)
    background_rgb: tuple[int, int, int] = DEFAULT_BACKGROUND_RGB
    backend: RenderBackendName = "auto"
    preview_format: PreviewFormat = "webp"
    preview_max_side: int = Field(default=480, ge=64, le=1280)
    preview_fps: int = Field(default=12, ge=1, le=30)
    ffmpeg_bin: str = "ffmpeg"
    mp4_crf: int = Field(default=20, ge=0, le=51)
    mp4_preset: str = "medium"
    cache_dir: Path | None = None
    # Studio Styles (see ``app.services.three_d.styles``).
    lighting_preset: LightingPresetName = LightingPresetName.STUDIO_SOFT
    shadow_catcher: ShadowCatcherFloorSettings = Field(
        default_factory=ShadowCatcherFloorSettings
    )
    studio_settings: RenderSettingsDTO | None = None
    # SSAA: render frames at ``ssaa_factor``× resolution then LANCZOS-downsample.
    # 2 ≈ practical supersampling; higher values mimic 4×/8× AA at CPU cost.
    ssaa_factor: int = Field(default=2, ge=1, le=4)
    # Optional Loop-style midpoint subdivision after load (0 = leave as-is).
    mesh_subdivisions: int = Field(default=0, ge=0, le=6)

    @classmethod
    def from_studio_settings(
        cls,
        settings: RenderSettingsDTO,
        *,
        fps: int = DEFAULT_FPS,
        frame_count: int = DEFAULT_FRAME_COUNT,
        backend: RenderBackendName = "auto",
        preview_format: PreviewFormat = "webp",
        cache_dir: Path | None = None,
        **overrides: object,
    ) -> RenderEngineConfig:
        """Build engine config from a validated ``RenderSettingsDTO``."""

        payload: dict[str, object] = {
            "width": settings.width,
            "height": settings.height,
            "fps": fps,
            "frame_count": frame_count,
            "fill_ratio": settings.fill_ratio,
            "fov_degrees": settings.fov_degrees,
            "elevation_degrees": settings.elevation_degrees,
            "background_rgb": settings.background_rgb,
            "backend": backend,
            "preview_format": preview_format,
            "cache_dir": cache_dir,
            "lighting_preset": settings.lighting_preset,
            "shadow_catcher": settings.shadow_catcher,
            "studio_settings": settings,
        }
        payload.update(overrides)
        return cls(**payload)  # type: ignore[arg-type]

    def resolved_lighting(self) -> LightingPresetDTO:
        if self.studio_settings is not None:
            return self.studio_settings.lighting
        return get_lighting_preset(self.lighting_preset)

    def resolved_shadow_catcher(self) -> ShadowCatcherFloorSettings:
        if self.studio_settings is not None:
            return self.studio_settings.shadow_catcher
        return self.shadow_catcher


class OrbitVideoResult(BaseModel):
    """In-memory encoded turntable artefacts (no disk spill)."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    mp4: io.BytesIO
    preview: io.BytesIO
    preview_mime: Literal["image/gif", "image/webp"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: int = Field(ge=1)
    frame_count: int = Field(ge=1)
    backend: str
    gl_backend: HeadlessGLBackend

    @property
    def mp4_bytes(self) -> bytes:
        return self.mp4.getvalue()

    @property
    def preview_bytes(self) -> bytes:
        return self.preview.getvalue()


@dataclass(slots=True)
class MeshGeometry:
    """CPU-side triangle mesh used by all backends."""

    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    bounds: MeshBounds
    source_format: MeshFormat
    source_digest: str
    # Per-vertex unit normals for smooth (Gouraud) shading. Always populated
    # by ``load_mesh_bytes`` / ``compute_vertex_normals``.
    normals: list[tuple[float, float, float]] | None = None

    @property
    def centered_vertices(self) -> list[tuple[float, float, float]]:
        cx, cy, cz = self.bounds.center
        return [(x - cx, y - cy, z - cz) for x, y, z in self.vertices]

    @property
    def resolved_normals(self) -> list[tuple[float, float, float]]:
        if self.normals is not None and len(self.normals) == len(self.vertices):
            return self.normals
        return compute_vertex_normals(self.vertices, self.faces)


# ---------------------------------------------------------------------------
# Headless GL bootstrap
# ---------------------------------------------------------------------------


def configure_headless_opengl() -> HeadlessGLBackend:
    """Prefer EGL, then OSMesa; fall back to pure-CPU software raster.

    Safe to call multiple times. Mutates process env for VTK / PyVista /
    moderngl consumers running inside isolated Docker images without X11.
    """

    os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
    os.environ.setdefault("MESA_GL_VERSION_OVERRIDE", "3.3")
    # Avoid accidental attempts to open a real DISPLAY socket in containers.
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    forced = (os.environ.get("THREE_D_GL_BACKEND") or "").strip().lower()
    if forced in {"egl", "osmesa", "software"}:
        _apply_gl_env(forced)  # type: ignore[arg-type]
        return forced  # type: ignore[return-value]

    for candidate in ("egl", "osmesa"):
        if _probe_gl_backend(candidate):  # type: ignore[arg-type]
            _apply_gl_env(candidate)  # type: ignore[arg-type]
            logger.info("Headless GL backend selected: %s", candidate)
            return candidate  # type: ignore[return-value]

    logger.warning(
        "Neither EGL nor OSMesa is usable; falling back to software rasteriser."
    )
    _apply_gl_env("software")
    return "software"


def _apply_gl_env(backend: HeadlessGLBackend) -> None:
    if backend == "egl":
        os.environ["VTK_DEFAULT_OPENGL_WINDOW"] = "vtkEGLRenderWindow"
        os.environ.pop("VTK_USE_OSMESA", None)
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    elif backend == "osmesa":
        os.environ["VTK_DEFAULT_OPENGL_WINDOW"] = "vtkOSOpenGLRenderWindow"
        os.environ["VTK_USE_OSMESA"] = "1"
        os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")
    else:
        os.environ.pop("VTK_DEFAULT_OPENGL_WINDOW", None)
        os.environ.pop("VTK_USE_OSMESA", None)


def _probe_gl_backend(backend: HeadlessGLBackend) -> bool:
    """Best-effort availability probe without hard-failing the import graph."""

    if backend == "software":
        return True
    try:
        if backend == "egl":
            # libEGL presence is enough to attempt vtkEGL later.
            return bool(
                shutil.which("eglinfo")
                or Path("/usr/lib/x86_64-linux-gnu/libEGL.so.1").exists()
                or Path("/usr/lib/libEGL.so.1").exists()
                or os.environ.get("NVIDIA_DRIVER_CAPABILITIES")
            )
        # OSMesa
        return bool(
            Path("/usr/lib/x86_64-linux-gnu/libOSMesa.so.8").exists()
            or Path("/usr/lib/libOSMesa.so.8").exists()
            or Path("/usr/lib/x86_64-linux-gnu/libOSMesa.so").exists()
        )
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Camera / orbit math
# ---------------------------------------------------------------------------


def compute_fit_distance(
    bounds: MeshBounds,
    *,
    fill_ratio: float = DEFAULT_FILL_RATIO,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
    aspect: float = DEFAULT_WIDTH / DEFAULT_HEIGHT,
) -> float:
    """Camera distance so the mesh occupies ``fill_ratio`` of the frame.

    Uses the vertical FOV and the projected bounding sphere. ``fill_ratio`` is
    clamped to the product requirement band ``[0.80, 0.85]``.
    """

    ratio = min(0.85, max(0.80, fill_ratio))
    fov_y = math.radians(fov_degrees)
    fov_x = 2.0 * math.atan(math.tan(fov_y * 0.5) * max(aspect, 1e-6))
    radius = bounds.radius
    # Distance where the sphere diameter fills ``ratio`` of the narrower FOV.
    limiting_fov = min(fov_x, fov_y)
    distance = radius / (ratio * math.tan(limiting_fov * 0.5))
    # Small padding so silhouette edges are never clipped by near-plane jitter.
    return max(distance * 1.02, radius * 1.5, 1e-3)


def build_orbit_poses(
    bounds: MeshBounds,
    *,
    frame_count: int = DEFAULT_FRAME_COUNT,
    fill_ratio: float = DEFAULT_FILL_RATIO,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
    elevation_degrees: float = 20.0,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[OrbitCameraPose]:
    """Evenly spaced 360° orbit around the (already-centred) mesh origin."""

    if frame_count < 2:
        raise ValueError("frame_count must be >= 2 for a closed orbit.")
    # Mesh is centred at origin after load; orbit around (0,0,0).
    target = (0.0, 0.0, 0.0)
    cx, cy, cz = bounds.center
    centred = MeshBounds(
        min_xyz=(bounds.min_xyz[0] - cx, bounds.min_xyz[1] - cy, bounds.min_xyz[2] - cz),
        max_xyz=(bounds.max_xyz[0] - cx, bounds.max_xyz[1] - cy, bounds.max_xyz[2] - cz),
    )
    distance = compute_fit_distance(
        centred,
        fill_ratio=fill_ratio,
        fov_degrees=fov_degrees,
        aspect=width / max(height, 1),
    )
    elev = math.radians(elevation_degrees)
    poses: list[OrbitCameraPose] = []
    for i in range(frame_count):
        azimuth = (2.0 * math.pi * i) / frame_count
        x = distance * math.cos(elev) * math.sin(azimuth)
        y = distance * math.sin(elev)
        z = distance * math.cos(elev) * math.cos(azimuth)
        poses.append(
            OrbitCameraPose(
                frame_index=i,
                azimuth_rad=azimuth,
                elevation_rad=elev,
                eye=(x, y, z),
                target=target,
                distance=distance,
            )
        )
    return poses


# ---------------------------------------------------------------------------
# Mesh I/O + local cache
# ---------------------------------------------------------------------------


class MeshBytesSource(Protocol):
    """Async-capable byte fetcher (S3 helper / httpx / in-memory)."""

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...


def detect_mesh_format(path_or_name: str | Path, data: bytes | None = None) -> MeshFormat:
    suffix = Path(path_or_name).suffix.lower()
    if suffix in _SUPPORTED_SUFFIXES:
        return _SUPPORTED_SUFFIXES[suffix]
    if data is not None:
        if data[:4] == b"glTF":
            return "glb"
        if data[:1] in (b"{", b" ") and b"\"asset\"" in data[:256]:
            return "gltf"
        if b"v " in data[:512] and b"f " in data[:8192]:
            return "obj"
    raise MeshLoadError(
        f"Unsupported mesh format for '{path_or_name}'. Expected .glb / .gltf / .obj."
    )


def mesh_cache_path(cache_dir: Path, digest: str, fmt: MeshFormat) -> Path:
    return cache_dir / f"{digest}.{fmt}"


def compute_vertex_normals(
    vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
) -> list[tuple[float, float, float]]:
    """Area-weighted smooth vertex normals (force Smooth Shading)."""

    accum = [[0.0, 0.0, 0.0] for _ in range(len(vertices))]
    for a, b, c in faces:
        if a < 0 or b < 0 or c < 0:
            continue
        if a >= len(vertices) or b >= len(vertices) or c >= len(vertices):
            continue
        n = _triangle_normal(vertices[a], vertices[b], vertices[c])
        # Weight by triangle area proxy (unnormalized cross length already in n
        # unit form — re-accumulate unit face normals equally for stability).
        for idx in (a, b, c):
            accum[idx][0] += n[0]
            accum[idx][1] += n[1]
            accum[idx][2] += n[2]
    return [_normalize((x, y, z)) for x, y, z in accum]


def subdivide_mesh_geometry(
    mesh: MeshGeometry,
    *,
    levels: int = 5,
    project_to_sphere: bool = False,
) -> MeshGeometry:
    """Midpoint-subdivide triangles for a high-poly smooth look.

    Each level splits every triangle into 4. ``levels >= 5`` yields studio-grade
    density on generated primitives (icosphere / blob fallbacks).

    When ``project_to_sphere`` is True (icosphere path), new vertices are
    re-projected onto the bounding sphere so the surface stays round.
    """

    if levels <= 0:
        normals = compute_vertex_normals(mesh.vertices, mesh.faces)
        return MeshGeometry(
            vertices=list(mesh.vertices),
            faces=list(mesh.faces),
            bounds=mesh.bounds,
            source_format=mesh.source_format,
            source_digest=mesh.source_digest,
            normals=normals,
        )

    verts: list[tuple[float, float, float]] = list(mesh.vertices)
    faces: list[tuple[int, int, int]] = list(mesh.faces)
    cx, cy, cz = mesh.bounds.center
    radius = max(mesh.bounds.radius, 1e-6)

    def _maybe_project(v: tuple[float, float, float]) -> tuple[float, float, float]:
        if not project_to_sphere:
            return v
        dx, dy, dz = v[0] - cx, v[1] - cy, v[2] - cz
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-9
        scale = radius / length
        return (cx + dx * scale, cy + dy * scale, cz + dz * scale)

    def _midpoint(
        i: int,
        j: int,
        cache: dict[tuple[int, int], int],
    ) -> int:
        key = (i, j) if i < j else (j, i)
        cached = cache.get(key)
        if cached is not None:
            return cached
        a, b = verts[i], verts[j]
        mid = _maybe_project(
            ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)
        )
        idx = len(verts)
        verts.append(mid)
        cache[key] = idx
        return idx

    for _ in range(levels):
        midpoint_cache: dict[tuple[int, int], int] = {}

        next_faces: list[tuple[int, int, int]] = []
        for i, j, k in faces:
            a = _midpoint(i, j, midpoint_cache)
            b = _midpoint(j, k, midpoint_cache)
            c = _midpoint(k, i, midpoint_cache)
            next_faces.extend(((i, a, c), (j, b, a), (k, c, b), (a, b, c)))
        faces = next_faces

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    normals = compute_vertex_normals(verts, faces)
    return MeshGeometry(
        vertices=verts,
        faces=faces,
        bounds=MeshBounds(
            min_xyz=(min(xs), min(ys), min(zs)),
            max_xyz=(max(xs), max(ys), max(zs)),
        ),
        source_format=mesh.source_format,
        source_digest=mesh.source_digest,
        normals=normals,
    )


def load_mesh_bytes(
    data: bytes,
    *,
    source_name: str = "mesh.glb",
    subdivisions: int = 0,
) -> MeshGeometry:
    """Decode mesh bytes into CPU geometry (trimesh preferred).

    Always attaches smooth ``compute_vertex_normals()``. Optional
    ``subdivisions`` (≥5 for studio primitives) densifies the mesh.
    """

    if not data:
        raise MeshLoadError("Mesh payload is empty.")
    fmt = detect_mesh_format(source_name, data)
    digest = hashlib.sha256(data).hexdigest()[:24]

    try:
        import trimesh  # type: ignore[import-untyped]
    except ImportError:
        if fmt != "obj":
            raise MeshLoadError(
                "trimesh is required to load GLB/GLTF. Install backend extras "
                "or provide a plain Wavefront OBJ for the software path."
            ) from None
        mesh = _load_obj_fallback(data, digest=digest)
        if subdivisions > 0:
            return subdivide_mesh_geometry(mesh, levels=subdivisions)
        normals = compute_vertex_normals(mesh.vertices, mesh.faces)
        return MeshGeometry(
            vertices=mesh.vertices,
            faces=mesh.faces,
            bounds=mesh.bounds,
            source_format=mesh.source_format,
            source_digest=mesh.source_digest,
            normals=normals,
        )

    try:
        loaded = trimesh.load(
            io.BytesIO(data),
            file_type=fmt,
            force="mesh",
            process=True,
        )
    except Exception as exc:  # noqa: BLE001 — vendor parsers raise many types
        raise MeshLoadError(f"Failed to parse {fmt} mesh: {exc}") from exc

    if isinstance(loaded, trimesh.Scene):
        geometries = [
            g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)
        ]
        if not geometries:
            raise MeshLoadError("GLTF/GLB scene contains no triangle meshes.")
        tri = trimesh.util.concatenate(geometries)
    elif isinstance(loaded, trimesh.Trimesh):
        tri = loaded
    else:
        raise MeshLoadError(f"Unsupported trimesh payload type: {type(loaded)!r}")

    if tri.vertices is None or len(tri.vertices) == 0:
        raise MeshLoadError("Mesh has no vertices.")
    faces = tri.faces
    if faces is None or len(faces) == 0:
        raise MeshLoadError("Mesh has no faces.")

    # Force smooth vertex normals via trimesh when available.
    try:
        tri.fix_normals()
    except Exception:  # noqa: BLE001
        logger.debug("trimesh.fix_normals failed; using CPU path", exc_info=True)

    vmin = tuple(float(x) for x in tri.bounds[0])
    vmax = tuple(float(x) for x in tri.bounds[1])
    vertices = [tuple(float(c) for c in row) for row in tri.vertices]
    tri_faces = [tuple(int(i) for i in face) for face in faces]
    mesh = MeshGeometry(
        vertices=vertices,  # type: ignore[arg-type]
        faces=tri_faces,  # type: ignore[arg-type]
        bounds=MeshBounds(min_xyz=vmin, max_xyz=vmax),  # type: ignore[arg-type]
        source_format=fmt,
        source_digest=digest,
        normals=None,
    )
    if subdivisions > 0:
        return subdivide_mesh_geometry(mesh, levels=subdivisions)
    mesh.normals = compute_vertex_normals(mesh.vertices, mesh.faces)
    return mesh


def _load_obj_fallback(data: bytes, *, digest: str) -> MeshGeometry:
    """Minimal OBJ loader used when trimesh is not installed (CI / unit tests)."""

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    text = data.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif parts[0] == "f" and len(parts) >= 4:
            idxs: list[int] = []
            for token in parts[1:]:
                idxs.append(int(token.split("/")[0]) - 1)
            for i in range(1, len(idxs) - 1):
                faces.append((idxs[0], idxs[i], idxs[i + 1]))
    if not vertices or not faces:
        raise MeshLoadError("OBJ fallback parser found no vertices/faces.")
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    normals = compute_vertex_normals(vertices, faces)
    return MeshGeometry(
        vertices=vertices,
        faces=faces,
        bounds=MeshBounds(
            min_xyz=(min(xs), min(ys), min(zs)),
            max_xyz=(max(xs), max(ys), max(zs)),
        ),
        source_format="obj",
        source_digest=digest,
        normals=normals,
    )


def write_mesh_cache(cache_dir: Path, data: bytes, fmt: MeshFormat) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:24]
    path = mesh_cache_path(cache_dir, digest, fmt)
    if not path.is_file():
        path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Frame backends
# ---------------------------------------------------------------------------


class FrameRendererBackend(ABC):
    """Strategy interface for producing one RGB24 frame."""

    name: str = "base"

    @abstractmethod
    def setup(self, mesh: MeshGeometry, config: RenderEngineConfig) -> None: ...

    @abstractmethod
    def render_frame(self, pose: OrbitCameraPose) -> bytes:
        """Return tightly packed RGB24 bytes of length ``width*height*3``."""

    @abstractmethod
    def close(self) -> None: ...


class SoftwareRasterBackend(FrameRendererBackend):
    """Dependency-light CPU rasteriser (tests / last-resort Docker fallback).

    Features: smooth vertex normals, elliptical Gaussian contact shadow, and
    2× SSAA (supersample → LANCZOS downsample) for studio-grade edges.
    """

    name = "software"

    def __init__(self) -> None:
        self._mesh: MeshGeometry | None = None
        self._config: RenderEngineConfig | None = None
        self._verts: list[tuple[float, float, float]] = []
        self._normals: list[tuple[float, float, float]] = []
        self._lighting: LightingPresetDTO | None = None
        self._mesh_radius: float = 1.0
        self._centered_min_y: float = -0.5

    def setup(self, mesh: MeshGeometry, config: RenderEngineConfig) -> None:
        self._mesh = mesh
        self._config = config
        self._verts = mesh.centered_vertices
        self._normals = mesh.resolved_normals
        self._lighting = config.resolved_lighting()
        self._centered_min_y = -0.5 * mesh.bounds.extents[1]
        self._mesh_radius = mesh.bounds.radius

    def render_frame(self, pose: OrbitCameraPose) -> bytes:
        if self._mesh is None or self._config is None or self._lighting is None:
            raise RenderEngineError("Software backend is not initialised.")
        cfg = self._config
        ssaa = max(1, int(cfg.ssaa_factor))
        raw = self._render_frame_at(pose, width=cfg.width * ssaa, height=cfg.height * ssaa)
        if ssaa == 1:
            return raw
        from PIL import Image

        try:
            resampling = Image.Resampling.LANCZOS
        except AttributeError:  # pragma: no cover
            resampling = Image.LANCZOS  # type: ignore[attr-defined]
        img = Image.frombytes("RGB", (cfg.width * ssaa, cfg.height * ssaa), raw)
        img = img.resize((cfg.width, cfg.height), resampling)
        return img.tobytes()

    def _render_frame_at(
        self,
        pose: OrbitCameraPose,
        *,
        width: int,
        height: int,
    ) -> bytes:
        assert self._mesh is not None and self._config is not None
        assert self._lighting is not None
        cfg = self._config
        lighting = self._lighting
        w, h = width, height
        depth = [float("inf")] * (w * h)
        pixels = bytearray(w * h * RGB24_BYTES_PER_PIXEL)
        bg = cfg.background_rgb
        for i in range(0, len(pixels), 3):
            pixels[i] = bg[0]
            pixels[i + 1] = bg[1]
            pixels[i + 2] = bg[2]

        view = _look_at_matrix(pose.eye, pose.target, pose.up)
        proj = _perspective_matrix(
            math.radians(cfg.fov_degrees), w / max(h, 1), 0.01, pose.distance * 20.0
        )
        mvp = _matmul4(proj, view)

        # Soft elliptical contact shadow (Gaussian-blurred) under the product.
        # Tessellated catcher mesh is skipped on the CPU path — a solid floor
        # slab reads as a hard horizon; the blurred ellipse grounds the object.
        self._composite_gaussian_contact_shadow(
            pixels,
            mvp=mvp,
            width=w,
            height=h,
        )

        normals = self._normals
        for face in self._mesh.faces:
            i0, i1, i2 = face
            tri = [self._verts[i0], self._verts[i1], self._verts[i2]]
            clip = [_transform_point(mvp, v) for v in tri]
            if any(p is None for p in clip):
                continue
            ndc = [p for p in clip if p is not None]
            screen = []
            for x, y, z in ndc:
                sx = (x * 0.5 + 0.5) * (w - 1)
                sy = (1.0 - (y * 0.5 + 0.5)) * (h - 1)
                screen.append((sx, sy, z))
            # True Gouraud: shade each vertex with smooth normals, then interpolate.
            colors: list[tuple[int, int, int]] = []
            for ni in (i0, i1, i2):
                shaded = shade_surface_lambert(normals[ni], lighting)
                colors.append(
                    (
                        int(min(255, 235 * shaded[0])),
                        int(min(255, 240 * shaded[1])),
                        int(min(255, 248 * shaded[2])),
                    )
                )
            _fill_triangle_gouraud(pixels, depth, w, h, screen, colors)
        return bytes(pixels)

    def _composite_gaussian_contact_shadow(
        self,
        pixels: bytearray,
        *,
        mvp: Mat4,
        width: int,
        height: int,
    ) -> None:
        """Elliptical soft shadow under the mesh, Gaussian-blurred via Pillow."""

        if self._config is None:
            return
        catcher = self._config.resolved_shadow_catcher()
        if not catcher.enabled or not catcher.receive_shadows:
            return

        from PIL import Image, ImageDraw, ImageFilter

        # Contact point at mesh bottom centre in centred coordinates.
        contact = (0.0, self._centered_min_y - catcher.y_offset, 0.0)
        projected = _transform_point(mvp, contact)
        if projected is None:
            return
        px = (projected[0] * 0.5 + 0.5) * (width - 1)
        py = (1.0 - (projected[1] * 0.5 + 0.5)) * (height - 1)

        # Ellipse size scales with mesh radius projected roughly to screen.
        rim = (self._mesh_radius * 0.85, self._centered_min_y, 0.0)
        rim_p = _transform_point(mvp, rim)
        if rim_p is None:
            radius_x = max(8.0, width * 0.12)
        else:
            rx = (rim_p[0] * 0.5 + 0.5) * (width - 1)
            radius_x = max(8.0, abs(rx - px) * (1.1 + catcher.shadow_softness))
        radius_y = max(4.0, radius_x * 0.38)

        shadow = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(shadow)
        strength = int(round(255 * catcher.shadow_strength * catcher.opacity))
        draw.ellipse(
            (
                px - radius_x,
                py - radius_y,
                px + radius_x,
                py + radius_y,
            ),
            fill=strength,
        )
        blur_radius = max(2.0, min(width, height) * 0.018 * (0.5 + catcher.shadow_softness))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        alpha = shadow.tobytes()
        for i, a in enumerate(alpha):
            if a == 0:
                continue
            t = a / 255.0
            off = i * 3
            # Soft dark umbra — grounds the product on the studio plate.
            pixels[off] = int(pixels[off] * (1.0 - 0.72 * t))
            pixels[off + 1] = int(pixels[off + 1] * (1.0 - 0.72 * t))
            pixels[off + 2] = int(pixels[off + 2] * (1.0 - 0.72 * t))

    def close(self) -> None:
        self._mesh = None
        self._config = None
        self._verts = []
        self._normals = []
        self._lighting = None
        self._mesh_radius = 1.0
        self._centered_min_y = -0.5


class PyVistaOffscreenBackend(FrameRendererBackend):
    """PyVista / VTK offscreen path (EGL or OSMesa via env)."""

    name = "pyvista"

    def __init__(self) -> None:
        self._plotter = None
        self._config: RenderEngineConfig | None = None

    def setup(self, mesh: MeshGeometry, config: RenderEngineConfig) -> None:
        try:
            import numpy as np
            import pyvista as pv
        except ImportError as exc:
            raise HeadlessGLError(
                "pyvista/numpy are required for the PyVista backend."
            ) from exc

        configure_headless_opengl()
        pv.OFF_SCREEN = True
        verts = np.asarray(mesh.centered_vertices, dtype=np.float64)
        faces_flat: list[int] = []
        for a, b, c in mesh.faces:
            faces_flat.extend((3, a, b, c))
        faces = np.asarray(faces_flat, dtype=np.int64)
        poly = pv.PolyData(verts, faces)
        # Force smooth shading normals (equivalent to compute_vertex_normals).
        try:
            poly = poly.compute_normals(
                cell_normals=False,
                point_normals=True,
                consistent_normals=True,
                inplace=False,
            )
        except Exception:  # noqa: BLE001
            logger.debug("PyVista compute_normals failed", exc_info=True)

        ssaa = max(1, int(config.ssaa_factor))
        plotter = pv.Plotter(
            off_screen=True,
            window_size=(config.width * ssaa, config.height * ssaa),
        )
        # Multi-sample AA when the VTK backend exposes it (≈ 8×).
        try:
            ren_win = getattr(plotter, "ren_win", None) or getattr(
                plotter, "render_window", None
            )
            if ren_win is not None and hasattr(ren_win, "SetMultiSamples"):
                ren_win.SetMultiSamples(8 if ssaa >= 2 else 0)
        except Exception:  # noqa: BLE001
            logger.debug("VTK SetMultiSamples unavailable", exc_info=True)

        plotter.set_background(
            [
                config.background_rgb[0] / 255.0,
                config.background_rgb[1] / 255.0,
                config.background_rgb[2] / 255.0,
            ]
        )
        plotter.add_mesh(
            poly,
            color=(0.82, 0.86, 0.92),
            smooth_shading=True,
            specular=0.35,
            specular_power=25,
        )

        # Shadow-catcher floor under the centred mesh.
        centered_min_y = -0.5 * mesh.bounds.extents[1]
        floor = build_shadow_catcher_floor(
            mesh_min_y=centered_min_y,
            mesh_radius=mesh.bounds.radius,
            settings=config.resolved_shadow_catcher(),
        )
        if floor is not None:
            floor_verts = np.asarray(floor.vertices, dtype=np.float64)
            floor_faces: list[int] = []
            for a, b, c in floor.faces:
                floor_faces.extend((3, a, b, c))
            floor_poly = pv.PolyData(
                floor_verts, np.asarray(floor_faces, dtype=np.int64)
            )
            # Near-invisible albedo — shadows read as soft contact on gradient /
            # transparent plates without a hard studio-table look.
            plotter.add_mesh(
                floor_poly,
                color=list(floor.settings.albedo_rgb),
                opacity=float(floor.settings.opacity),
                smooth_shading=True,
                specular=0.0,
            )

        _apply_pyvista_lighting(plotter, config.resolved_lighting())
        plotter.camera.view_angle = float(config.fov_degrees)
        self._plotter = plotter
        self._config = config

    def render_frame(self, pose: OrbitCameraPose) -> bytes:
        if self._plotter is None or self._config is None:
            raise RenderEngineError("PyVista backend is not initialised.")
        cam = self._plotter.camera
        cam.position = pose.eye
        cam.focal_point = pose.target
        cam.up = pose.up
        self._plotter.render()
        img = self._plotter.screenshot(return_img=True, transparent_background=False)
        # screenshot returns HxWx3/4 uint8
        if img.shape[2] == 4:
            img = img[:, :, :3]
        ssaa = max(1, int(self._config.ssaa_factor))
        expected = self._config.width * self._config.height * RGB24_BYTES_PER_PIXEL
        if ssaa > 1:
            import numpy as np
            from PIL import Image

            arr = np.ascontiguousarray(img[:, :, :3], dtype=np.uint8)
            pil = Image.fromarray(arr, mode="RGB")
            try:
                resampling = Image.Resampling.LANCZOS
            except AttributeError:  # pragma: no cover
                resampling = Image.LANCZOS  # type: ignore[attr-defined]
            pil = pil.resize(
                (self._config.width, self._config.height),
                resampling,
            )
            raw = pil.tobytes()
        else:
            raw = memoryview(img).tobytes() if hasattr(img, "tobytes") else bytes(img)
            if len(raw) != expected:
                import numpy as np

                arr = np.ascontiguousarray(img[:, :, :3], dtype=np.uint8)
                raw = arr.tobytes()
        if len(raw) != expected:
            raise RenderEngineError(
                f"Unexpected frame size {len(raw)} (expected {expected})."
            )
        return raw

    def close(self) -> None:
        if self._plotter is not None:
            try:
                self._plotter.close()
            except Exception:  # noqa: BLE001
                logger.debug("PyVista plotter close failed", exc_info=True)
        self._plotter = None
        self._config = None


def _apply_pyvista_lighting(plotter: object, preset: LightingPresetDTO) -> None:
    """Replace default VTK headlight with a Studio Styles lighting rig."""

    try:
        import pyvista as pv
    except ImportError:
        return

    remove_all = getattr(plotter, "remove_all_lights", None)
    if callable(remove_all):
        remove_all()

    # Ambient via a very soft fill light when VTK ambient API is limited.
    ambient = preset.ambient_intensity
    if ambient > 0.0:
        amb = pv.Light(
            position=(0.0, 8.0, 0.0),
            focal_point=(0.0, 0.0, 0.0),
            color=list(preset.ambient_rgb),
            intensity=float(ambient),
            positional=True,
        )
        amb.cone_angle = 90.0
        plotter.add_light(amb)  # type: ignore[attr-defined]

    for src in preset.lights:
        light = pv.Light(
            position=list(src.position),
            focal_point=(0.0, 0.0, 0.0),
            color=list(src.color_rgb),
            intensity=float(src.intensity),
            positional=bool(src.positional),
        )
        # Softness ≈ wider cone / lower specular punch.
        light.cone_angle = 25.0 + 55.0 * float(src.softness)
        plotter.add_light(light)  # type: ignore[attr-defined]


def create_frame_backend(
    preferred: RenderBackendName,
    *,
    gl_backend: HeadlessGLBackend,
) -> FrameRendererBackend:
    """Resolve the concrete raster backend with graceful degradation."""

    order: list[str]
    if preferred == "software":
        order = ["software"]
    elif preferred == "pyvista":
        order = ["pyvista", "software"]
    elif preferred == "moderngl":
        order = ["moderngl", "software"]
    else:
        if gl_backend == "software":
            order = ["software"]
        else:
            order = ["pyvista", "moderngl", "software"]

    errors: list[str] = []
    for name in order:
        try:
            if name == "pyvista":
                return PyVistaOffscreenBackend()
            if name == "moderngl":
                # Lambert + shadow-plane implementation (separate module).
                from app.services.three_d.moderngl_renderer import (
                    ModernglOffscreenBackend,
                )

                return ModernglOffscreenBackend()
            return SoftwareRasterBackend()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    raise HeadlessGLError(
        "Unable to construct a frame backend. Tried: " + "; ".join(errors)
    )


# ---------------------------------------------------------------------------
# Tiny linear-algebra helpers (no numpy required on the software path)
# ---------------------------------------------------------------------------

Mat4 = list[list[float]]
Vec3 = tuple[float, float, float]


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(v: Vec3) -> Vec3:
    length = math.sqrt(_dot(v, v)) or 1e-9
    return (v[0] / length, v[1] / length, v[2] / length)


def _triangle_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    return _normalize(_cross((b[0] - a[0], b[1] - a[1], b[2] - a[2]), (c[0] - a[0], c[1] - a[1], c[2] - a[2])))


def _look_at_matrix(eye: Vec3, target: Vec3, up: Vec3) -> Mat4:
    f = _normalize((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    s = _normalize(_cross(f, up))
    u = _cross(s, f)
    return [
        [s[0], s[1], s[2], -_dot(s, eye)],
        [u[0], u[1], u[2], -_dot(u, eye)],
        [-f[0], -f[1], -f[2], _dot(f, eye)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _perspective_matrix(fov_y: float, aspect: float, z_near: float, z_far: float) -> Mat4:
    f = 1.0 / math.tan(fov_y * 0.5)
    nf = 1.0 / (z_near - z_far)
    return [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (z_far + z_near) * nf, 2.0 * z_far * z_near * nf],
        [0.0, 0.0, -1.0, 0.0],
    ]


def _matmul4(a: Mat4, b: Mat4) -> Mat4:
    out: Mat4 = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return out


def _transform_point(m: Mat4, v: Vec3) -> Vec3 | None:
    x = m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2] + m[0][3]
    y = m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2] + m[1][3]
    z = m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2] + m[2][3]
    w = m[3][0] * v[0] + m[3][1] * v[1] + m[3][2] * v[2] + m[3][3]
    if abs(w) < 1e-12:
        return None
    return (x / w, y / w, z / w)


def _fill_triangle(
    pixels: bytearray,
    depth: list[float],
    width: int,
    height: int,
    pts: Sequence[tuple[float, float, float]],
    color: tuple[int, int, int],
) -> None:
    _fill_triangle_gouraud(pixels, depth, width, height, pts, (color, color, color))


def _fill_triangle_gouraud(
    pixels: bytearray,
    depth: list[float],
    width: int,
    height: int,
    pts: Sequence[tuple[float, float, float]],
    colors: Sequence[tuple[int, int, int]],
) -> None:
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = pts
    c0, c1, c2 = colors
    min_x = max(0, int(math.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(math.ceil(max(x0, x1, x2))))
    min_y = max(0, int(math.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(math.ceil(max(y0, y1, y2))))
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(area) < 1e-8:
        return
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            w0 = ((x1 - x) * (y2 - y) - (x2 - x) * (y1 - y)) / area
            w1 = ((x2 - x) * (y0 - y) - (x0 - x) * (y2 - y)) / area
            w2 = 1.0 - w0 - w1
            if w0 < 0.0 or w1 < 0.0 or w2 < 0.0:
                continue
            z = w0 * z0 + w1 * z1 + w2 * z2
            idx = y * width + x
            if z >= depth[idx]:
                continue
            depth[idx] = z
            off = idx * 3
            pixels[off] = int(w0 * c0[0] + w1 * c1[0] + w2 * c2[0])
            pixels[off + 1] = int(w0 * c0[1] + w1 * c1[1] + w2 * c2[1])
            pixels[off + 2] = int(w0 * c0[2] + w1 * c1[2] + w2 * c2[2])


# ---------------------------------------------------------------------------
# FFmpeg pipe encoder
# ---------------------------------------------------------------------------


class FFmpegPipeEncoder:
    """Stream raw RGB24 frames into an in-memory container via FFmpeg stdin."""

    def __init__(
        self,
        *,
        argv: list[str],
        width: int,
        height: int,
        label: str = "ffmpeg",
    ) -> None:
        self._argv = argv
        self._width = width
        self._height = height
        self._label = label
        self._proc: subprocess.Popen[bytes] | None = None
        self._stdout_chunks: list[bytes] = []
        self._stderr = b""
        self._reader: threading.Thread | None = None
        self._frame_bytes = width * height * RGB24_BYTES_PER_PIXEL
        self._frames_written = 0

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close(abort=exc_type is not None)

    def start(self) -> None:
        if self._proc is not None:
            return
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise FFmpegEncodeError(
                f"FFmpeg binary not found ({self._argv[0]!r}). "
                "Install ffmpeg in the image / PATH."
            ) from exc
        assert self._proc.stdout is not None
        self._reader = threading.Thread(
            target=self._pump_stdout,
            name=f"{self._label}-stdout",
            daemon=True,
        )
        self._reader.start()

    def write_frame(self, rgb24: bytes) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise FFmpegEncodeError(f"{self._label} process is not running.")
        if len(rgb24) != self._frame_bytes:
            raise FFmpegEncodeError(
                f"Frame has {len(rgb24)} bytes; expected {self._frame_bytes}."
            )
        try:
            self._proc.stdin.write(rgb24)
        except BrokenPipeError as exc:
            self._stderr = (self._proc.stderr.read() if self._proc.stderr else b"")
            raise FFmpegEncodeError(
                f"{self._label} stdin broken: {self._stderr[-2000:]!r}"
            ) from exc
        self._frames_written += 1

    def finish(self) -> io.BytesIO:
        if self._proc is None:
            raise FFmpegEncodeError(f"{self._label} was never started.")
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
        if self._reader is not None:
            self._reader.join(timeout=120)
        stderr = self._proc.stderr.read() if self._proc.stderr else b""
        self._stderr = stderr
        code = self._proc.wait(timeout=120)
        payload = b"".join(self._stdout_chunks)
        self._proc = None
        if code != 0 or not payload:
            raise FFmpegEncodeError(
                f"{self._label} failed (exit={code}, frames={self._frames_written}): "
                f"{stderr[-4000:]!r}"
            )
        buf = io.BytesIO(payload)
        buf.seek(0)
        return buf

    def close(self, *, abort: bool = False) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        if abort and proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
        self._proc = None

    def _pump_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            chunk = self._proc.stdout.read(1024 * 256)
            if not chunk:
                break
            self._stdout_chunks.append(chunk)


def _ffmpeg_global_flags(ffmpeg_bin: str) -> list[str]:
    """Return portable global flags; omit ``-hide_banner`` when unsupported."""

    flags = ["-loglevel", "error", "-y"]
    if ffmpeg_supports_hide_banner(ffmpeg_bin):
        return ["-hide_banner", *flags]
    return flags


@lru_cache(maxsize=16)
def ffmpeg_supports_hide_banner(ffmpeg_bin: str) -> bool:
    """Probe whether ``ffmpeg_bin`` accepts ``-hide_banner`` (Windows builds vary)."""

    resolved = shutil.which(ffmpeg_bin) or ffmpeg_bin
    try:
        proc = subprocess.run(
            [resolved, "-hide_banner", "-version"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return False
    err = (proc.stderr or b"").decode("utf-8", errors="replace").lower()
    out = (proc.stdout or b"").decode("utf-8", errors="replace").lower()
    combined = f"{err}\n{out}"
    if "unrecognized option" in combined and "hide_banner" in combined:
        return False
    if "option not found" in combined and "hide_banner" in combined:
        return False
    return proc.returncode == 0


@lru_cache(maxsize=16)
def ffmpeg_mp4_movflags(ffmpeg_bin: str) -> str:
    """Pick MP4 ``-movflags`` compatible with pipe output on this FFmpeg build.

    Modern builds prefer ``frag_keyframe+empty_moov+default_base_moof``; older
    Windows nightlies (e.g. N-55702) reject ``default_base_moof`` and need the
    shorter ``frag_keyframe+empty_moov`` form.
    """

    preferred = "frag_keyframe+empty_moov+default_base_moof"
    fallback = "frag_keyframe+empty_moov"
    resolved = shutil.which(ffmpeg_bin) or ffmpeg_bin
    # Tiny 2x2 RGB frame — enough to exercise the muxer header path.
    probe_frame = bytes([0, 0, 0]) * 4
    for flags in (preferred, fallback):
        argv = [
            resolved,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "2x2",
            "-r",
            "1",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-movflags",
            flags,
            "-f",
            "mp4",
            "pipe:1",
        ]
        try:
            proc = subprocess.run(
                argv,
                input=probe_frame,
                capture_output=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            continue
        if proc.returncode == 0 and proc.stdout:
            return flags
    return fallback


def build_mp4_ffmpeg_argv(
    *,
    ffmpeg_bin: str,
    width: int,
    height: int,
    fps: int,
    crf: int = 20,
    preset: str = "medium",
) -> list[str]:
    return [
        ffmpeg_bin,
        *_ffmpeg_global_flags(ffmpeg_bin),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-movflags",
        ffmpeg_mp4_movflags(ffmpeg_bin),
        "-f",
        "mp4",
        "pipe:1",
    ]


def build_preview_ffmpeg_argv(
    *,
    ffmpeg_bin: str,
    width: int,
    height: int,
    fps: int,
    preview_format: PreviewFormat,
    preview_max_side: int,
    preview_fps: int,
) -> list[str]:
    scale = (
        f"scale='min({preview_max_side},iw)':-2:flags=lanczos"
        if width >= height
        else f"scale=-2:'min({preview_max_side},ih)':flags=lanczos"
    )
    fps_filter = f"fps={preview_fps}"
    base = [
        ffmpeg_bin,
        *_ffmpeg_global_flags(ffmpeg_bin),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
    ]
    if preview_format == "webp":
        return [
            *base,
            "-vf",
            f"{fps_filter},{scale}",
            "-c:v",
            "libwebp",
            "-lossless",
            "0",
            "-compression_level",
            "4",
            "-q:v",
            "50",
            "-loop",
            "0",
            "-f",
            "webp",
            "pipe:1",
        ]
    # GIF with palette for acceptable quality without disk palette files.
    return [
        *base,
        "-vf",
        f"{fps_filter},{scale},split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer",
        "-loop",
        "0",
        "-f",
        "gif",
        "pipe:1",
    ]


# ---------------------------------------------------------------------------
# Main renderer (context manager)
# ---------------------------------------------------------------------------


class Offscreen3DRenderer:
    """Autonomous headless turntable renderer.

    Usage::

        with Offscreen3DRenderer(config) as renderer:
            renderer.load_mesh_file(path)
            result = renderer.render_orbit_video()
            upload(result.mp4_bytes)
    """

    def __init__(self, config: RenderEngineConfig | None = None) -> None:
        self._config = config or RenderEngineConfig()
        self._gl_backend: HeadlessGLBackend = "software"
        self._frame_backend: FrameRendererBackend | None = None
        self._mesh: MeshGeometry | None = None
        self._poses: list[OrbitCameraPose] = []
        self._ffmpeg_procs: list[FFmpegPipeEncoder] = []
        self._entered = False
        self._closed = False
        if self._config.cache_dir is None:
            cache = Path(tempfile.gettempdir()) / "ai-card-master" / "three_d_mesh_cache"
        else:
            cache = self._config.cache_dir
        self._cache_dir = cache

    @property
    def config(self) -> RenderEngineConfig:
        return self._config

    @property
    def gl_backend(self) -> HeadlessGLBackend:
        return self._gl_backend

    @property
    def mesh(self) -> MeshGeometry | None:
        return self._mesh

    def __enter__(self) -> Self:
        if self._closed:
            raise RenderEngineError("Renderer was already closed.")
        self._gl_backend = configure_headless_opengl()
        self._frame_backend = create_frame_backend(
            self._config.backend,
            gl_backend=self._gl_backend,
        )
        self._entered = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Release GL resources and kill any lingering FFmpeg children."""

        self._closed = True
        for enc in list(self._ffmpeg_procs):
            try:
                enc.close(abort=True)
            except Exception:  # noqa: BLE001
                logger.debug("FFmpeg abort close failed", exc_info=True)
        self._ffmpeg_procs.clear()
        if self._frame_backend is not None:
            try:
                self._frame_backend.close()
            except Exception:  # noqa: BLE001
                logger.debug("Frame backend close failed", exc_info=True)
        self._frame_backend = None
        self._mesh = None
        self._poses = []
        self._entered = False

    def load_mesh_bytes(self, data: bytes, *, source_name: str = "mesh.glb") -> MeshGeometry:
        self._ensure_open()
        mesh = load_mesh_bytes(
            data,
            source_name=source_name,
            subdivisions=self._config.mesh_subdivisions,
        )
        # Persist a content-addressed local cache copy for subsequent jobs.
        try:
            write_mesh_cache(self._cache_dir, data, mesh.source_format)
        except OSError:
            logger.debug("Mesh cache write skipped", exc_info=True)
        return self._bind_mesh(mesh)

    def load_mesh_file(self, path: str | Path) -> MeshGeometry:
        self._ensure_open()
        file_path = Path(path)
        if not file_path.is_file():
            # Content-addressed cache hit by digest filename.
            cached = self._cache_dir / file_path.name
            if cached.is_file():
                file_path = cached
            else:
                raise MeshLoadError(f"Mesh file not found: {path}")
        data = file_path.read_bytes()
        return self.load_mesh_bytes(data, source_name=file_path.name)

    async def load_mesh_from_s3(
        self,
        object_key: str,
        *,
        storage: MeshBytesSource,
        max_bytes: int,
        source_name: str | None = None,
    ) -> MeshGeometry:
        """Download from S3 (or compatible), cache locally, then bind."""

        self._ensure_open()
        key = object_key.strip()
        if not key:
            raise MeshLoadError("S3 object_key must not be empty.")
        name = source_name or Path(key).name or "mesh.glb"
        fmt = detect_mesh_format(name)
        # Soft cache keyed by object path (stable across worker restarts).
        key_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        key_cached = mesh_cache_path(self._cache_dir, key_digest, fmt)
        if key_cached.is_file():
            return self.load_mesh_file(key_cached)
        data = await storage.download_bytes(object_key=key, max_bytes=max_bytes)
        resolved_fmt = detect_mesh_format(name, data)
        # Content-addressed cache + alias by object key for fast reloads.
        content_path = write_mesh_cache(self._cache_dir, data, resolved_fmt)
        if key_cached != content_path:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                if not key_cached.is_file():
                    key_cached.write_bytes(data)
            except OSError:
                logger.debug("Key-aliased mesh cache write skipped", exc_info=True)
        return self.load_mesh_bytes(content_path.read_bytes(), source_name=name)

    def _bind_mesh(self, mesh: MeshGeometry) -> MeshGeometry:
        assert self._frame_backend is not None
        self._mesh = mesh
        self._poses = build_orbit_poses(
            mesh.bounds,
            frame_count=self._config.frame_count,
            fill_ratio=self._config.fill_ratio,
            fov_degrees=self._config.fov_degrees,
            elevation_degrees=self._config.elevation_degrees,
            width=self._config.width,
            height=self._config.height,
        )
        self._frame_backend.setup(mesh, self._config)
        return mesh

    def iter_orbit_frames(self) -> Iterator[bytes]:
        """Yield RGB24 frames for the full 360° orbit (in-memory only)."""

        self._ensure_ready()
        assert self._frame_backend is not None
        for pose in self._poses:
            yield self._frame_backend.render_frame(pose)

    def render_orbit_video(
        self,
        *,
        on_frame: Callable[[int, int], None] | None = None,
    ) -> OrbitVideoResult:
        """Render the orbit into MP4, release buffers, then encode GIF/WebP.

        Dual-encode RAM shield: never run both FFmpeg pipes concurrently.
        Pass 1 streams frames into H.264 MP4; after ``finish()`` the encoder and
        frame scratch are dropped via ``del`` / ``gc.collect()``. Pass 2 re-renders
        the orbit into the lightweight preview container only.
        """

        self._ensure_ready()
        cfg = self._config
        assert self._frame_backend is not None

        mp4 = FFmpegPipeEncoder(
            argv=build_mp4_ffmpeg_argv(
                ffmpeg_bin=cfg.ffmpeg_bin,
                width=cfg.width,
                height=cfg.height,
                fps=cfg.fps,
                crf=cfg.mp4_crf,
                preset=cfg.mp4_preset,
            ),
            width=cfg.width,
            height=cfg.height,
            label="ffmpeg-mp4",
        )
        self._ffmpeg_procs.append(mp4)
        mp4_buf: io.BytesIO
        try:
            mp4.start()
            for frame_index, frame in enumerate(self.iter_orbit_frames()):
                mp4.write_frame(frame)
                if on_frame is not None:
                    on_frame(frame_index, cfg.frame_count)
            mp4_buf = mp4.finish()
        except Exception:
            mp4.close(abort=True)
            raise
        finally:
            if mp4 in self._ffmpeg_procs:
                self._ffmpeg_procs.remove(mp4)
            # Drop MP4 encoder / stdin buffers before starting the preview pipe.
            del mp4
            gc.collect()

        preview = FFmpegPipeEncoder(
            argv=build_preview_ffmpeg_argv(
                ffmpeg_bin=cfg.ffmpeg_bin,
                width=cfg.width,
                height=cfg.height,
                fps=cfg.fps,
                preview_format=cfg.preview_format,
                preview_max_side=cfg.preview_max_side,
                preview_fps=cfg.preview_fps,
            ),
            width=cfg.width,
            height=cfg.height,
            label=f"ffmpeg-{cfg.preview_format}",
        )
        self._ffmpeg_procs.append(preview)
        try:
            preview.start()
            for frame_index, frame in enumerate(self.iter_orbit_frames()):
                preview.write_frame(frame)
                # Preview pass does not advance Celery progress (already at 100%
                # of orbit after MP4); keep hook available for diagnostics.
                if on_frame is not None and frame_index == 0:
                    on_frame(cfg.frame_count - 1, cfg.frame_count)
            preview_buf = preview.finish()
        except Exception:
            preview.close(abort=True)
            raise
        finally:
            if preview in self._ffmpeg_procs:
                self._ffmpeg_procs.remove(preview)
            del preview
            gc.collect()

        mime: Literal["image/gif", "image/webp"] = (
            "image/webp" if cfg.preview_format == "webp" else "image/gif"
        )
        return OrbitVideoResult(
            mp4=mp4_buf,
            preview=preview_buf,
            preview_mime=mime,
            width=cfg.width,
            height=cfg.height,
            fps=cfg.fps,
            frame_count=cfg.frame_count,
            backend=self._frame_backend.name,
            gl_backend=self._gl_backend,
        )

    def _ensure_open(self) -> None:
        if self._closed or not self._entered or self._frame_backend is None:
            raise RenderEngineError(
                "Offscreen3DRenderer must be used as a context manager."
            )

    def _ensure_ready(self) -> None:
        self._ensure_open()
        if self._mesh is None or not self._poses:
            raise RenderEngineError("Load a mesh before rendering frames.")


__all__ = [
    "DEFAULT_FILL_RATIO",
    "DEFAULT_FPS",
    "DEFAULT_FRAME_COUNT",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "FFmpegEncodeError",
    "FFmpegPipeEncoder",
    "FrameRendererBackend",
    "HeadlessGLError",
    "MeshBounds",
    "MeshGeometry",
    "MeshLoadError",
    "Offscreen3DRenderer",
    "OrbitCameraPose",
    "OrbitVideoResult",
    "RenderEngineConfig",
    "RenderEngineError",
    "SoftwareRasterBackend",
    "build_mp4_ffmpeg_argv",
    "build_orbit_poses",
    "build_preview_ffmpeg_argv",
    "compute_fit_distance",
    "compute_vertex_normals",
    "configure_headless_opengl",
    "create_frame_backend",
    "detect_mesh_format",
    "ffmpeg_mp4_movflags",
    "ffmpeg_supports_hide_banner",
    "load_mesh_bytes",
    "subdivide_mesh_geometry",
]
