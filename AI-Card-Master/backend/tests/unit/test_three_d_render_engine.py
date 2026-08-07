"""Unit tests for headless orbital 3D render engine."""

from __future__ import annotations

import io
import math
import shutil
from pathlib import Path

import pytest

from app.services.three_d.render_engine import (
    DEFAULT_FILL_RATIO,
    FFmpegPipeEncoder,
    MeshBounds,
    Offscreen3DRenderer,
    OrbitVideoResult,
    RenderEngineConfig,
    RenderEngineError,
    SoftwareRasterBackend,
    build_mp4_ffmpeg_argv,
    build_orbit_poses,
    build_preview_ffmpeg_argv,
    compute_fit_distance,
    configure_headless_opengl,
    load_mesh_bytes,
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


def test_compute_fit_distance_keeps_fill_ratio_band() -> None:
    bounds = MeshBounds(min_xyz=(-1.0, -1.0, -1.0), max_xyz=(1.0, 1.0, 1.0))
    for ratio in (0.80, 0.825, 0.85):
        dist = compute_fit_distance(bounds, fill_ratio=ratio, fov_degrees=35.0, aspect=16 / 9)
        assert dist > bounds.radius
        # Larger fill → closer camera.
    near = compute_fit_distance(bounds, fill_ratio=0.85)
    far = compute_fit_distance(bounds, fill_ratio=0.80)
    assert near < far
    # Out-of-band inputs are clamped into [0.80, 0.85].
    assert compute_fit_distance(bounds, fill_ratio=0.5) == compute_fit_distance(
        bounds, fill_ratio=0.80
    )
    assert compute_fit_distance(bounds, fill_ratio=0.99) == compute_fit_distance(
        bounds, fill_ratio=0.85
    )


def test_build_orbit_poses_covers_full_turn() -> None:
    bounds = MeshBounds(min_xyz=(-2.0, -1.0, -1.5), max_xyz=(2.0, 1.0, 1.5))
    poses = build_orbit_poses(bounds, frame_count=24, fill_ratio=DEFAULT_FILL_RATIO)
    assert len(poses) == 24
    assert poses[0].azimuth_rad == pytest.approx(0.0)
    assert poses[-1].azimuth_rad == pytest.approx(2 * math.pi * 23 / 24)
    # Eyes stay on a sphere around the origin (centred mesh).
    for pose in poses:
        radius = math.sqrt(sum(c * c for c in pose.eye))
        assert radius == pytest.approx(pose.distance, rel=1e-6)
        assert pose.target == (0.0, 0.0, 0.0)


def test_load_obj_and_software_frame_size(tmp_path: Path) -> None:
    mesh = load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
    assert mesh.source_format == "obj"
    assert len(mesh.faces) == 12
    cfg = RenderEngineConfig(
        width=160,
        height=90,
        frame_count=8,
        fps=8,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    backend = SoftwareRasterBackend()
    backend.setup(mesh, cfg)
    poses = build_orbit_poses(mesh.bounds, frame_count=8, width=160, height=90)
    frame = backend.render_frame(poses[0])
    assert len(frame) == 160 * 90 * 3
    # Background is not the only colour — mesh contributed pixels.
    assert frame != bytes([24, 28, 36]) * (160 * 90)
    backend.close()


def test_offscreen_renderer_context_cleanup(tmp_path: Path) -> None:
    cfg = RenderEngineConfig(
        width=64,
        height=64,
        frame_count=4,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    with Offscreen3DRenderer(cfg) as renderer:
        renderer.load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
        frames = list(renderer.iter_orbit_frames())
        assert len(frames) == 4
        assert all(len(f) == 64 * 64 * 3 for f in frames)
    with pytest.raises(RenderEngineError):
        renderer.load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")


def test_ffmpeg_argv_builders() -> None:
    mp4 = build_mp4_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        width=1280,
        height=720,
        fps=24,
        crf=20,
        preset="medium",
    )
    assert mp4[0] == "ffmpeg"
    assert "libx264" in mp4
    assert "yuv420p" in mp4
    assert "medium" in mp4
    assert "20" in mp4
    assert "pipe:0" in mp4
    assert "pipe:1" in mp4

    webp = build_preview_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        width=1280,
        height=720,
        fps=24,
        preview_format="webp",
        preview_max_side=480,
        preview_fps=12,
    )
    assert "libwebp" in webp
    assert "webp" in webp

    gif = build_preview_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        width=1280,
        height=720,
        fps=24,
        preview_format="gif",
        preview_max_side=480,
        preview_fps=12,
    )
    assert "gif" in gif
    assert any("palettegen" in part for part in gif)


def test_configure_headless_opengl_returns_known_backend() -> None:
    backend = configure_headless_opengl()
    assert backend in {"egl", "osmesa", "software"}


def test_render_orbit_video_with_fake_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tee encode path without requiring a real FFmpeg binary."""

    class _FakeEncoder:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.frames: list[bytes] = []
            self._aborted = False

        def start(self) -> None:
            return None

        def write_frame(self, rgb24: bytes) -> None:
            self.frames.append(rgb24)

        def finish(self) -> io.BytesIO:
            label = str(self.kwargs.get("label", ""))
            if "mp4" in label:
                return io.BytesIO(b"\x00\x00\x00\x18ftypisomfake-mp4")
            return io.BytesIO(b"RIFF\x00\x00\x00\x00WEBP")

        def close(self, *, abort: bool = False) -> None:
            self._aborted = abort

    created: list[_FakeEncoder] = []

    def _factory(**kwargs: object) -> _FakeEncoder:
        enc = _FakeEncoder(**kwargs)
        created.append(enc)
        return enc

    monkeypatch.setattr(
        "app.services.three_d.render_engine.FFmpegPipeEncoder",
        _factory,
    )

    cfg = RenderEngineConfig(
        width=64,
        height=64,
        frame_count=6,
        fps=6,
        backend="software",
        preview_format="webp",
        cache_dir=tmp_path / "cache",
    )
    with Offscreen3DRenderer(cfg) as renderer:
        renderer.load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
        result = renderer.render_orbit_video()

    assert isinstance(result, OrbitVideoResult)
    assert result.frame_count == 6
    assert result.backend == "software"
    assert result.preview_mime == "image/webp"
    assert result.mp4_bytes.startswith(b"\x00\x00\x00\x18ftyp")
    assert result.preview_bytes.startswith(b"RIFF")
    assert len(created) == 2
    assert all(len(enc.frames) == 6 for enc in created)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_ffmpeg_pipe_encoder_roundtrip_smoke() -> None:
    """Optional smoke: real FFmpeg accepts one tiny RGB frame into MP4."""

    from app.services.three_d.errors import FFmpegEncodeError

    width, height = 64, 64
    argv = build_mp4_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        width=width,
        height=height,
        fps=1,
        crf=28,
        preset="ultrafast",
    )
    frame = bytes([40, 80, 120]) * (width * height)
    try:
        with FFmpegPipeEncoder(argv=argv, width=width, height=height, label="smoke") as enc:
            enc.write_frame(frame)
            buf = enc.finish()
    except FFmpegEncodeError as exc:
        pytest.skip(f"System ffmpeg is not usable for raw RGB pipe encode: {exc}")
    assert len(buf.getvalue()) > 32


def test_load_mesh_from_local_cache_file(tmp_path: Path) -> None:
    cfg = RenderEngineConfig(
        width=64,
        height=64,
        frame_count=2,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    mesh_path = tmp_path / "product.obj"
    mesh_path.write_bytes(_CUBE_OBJ)
    with Offscreen3DRenderer(cfg) as renderer:
        mesh = renderer.load_mesh_file(mesh_path)
        assert mesh.bounds.radius > 0
        cached_files = list((tmp_path / "cache").glob("*.obj"))
        assert cached_files


def test_s3_load_uses_download_bytes(tmp_path: Path) -> None:
    class _FakeStorage:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
            self.calls.append((object_key, max_bytes))
            return _CUBE_OBJ

    cfg = RenderEngineConfig(
        width=64,
        height=64,
        frame_count=2,
        backend="software",
        cache_dir=tmp_path / "cache",
    )
    storage = _FakeStorage()

    async def _run() -> None:
        with Offscreen3DRenderer(cfg) as renderer:
            mesh = await renderer.load_mesh_from_s3(
                "three-d/u/t/glb.obj",
                storage=storage,
                max_bytes=1024 * 1024,
                source_name="cube.obj",
            )
            assert len(mesh.vertices) == 8
        assert storage.calls == [("three-d/u/t/glb.obj", 1024 * 1024)]

    import asyncio

    asyncio.run(_run())


def test_renderer_must_be_context_manager() -> None:
    renderer = Offscreen3DRenderer(RenderEngineConfig(backend="software", frame_count=2))
    with pytest.raises(RenderEngineError):
        renderer.load_mesh_bytes(_CUBE_OBJ, source_name="cube.obj")
