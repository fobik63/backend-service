"""Shared 3D engine errors surfaced to the API / workers."""

from __future__ import annotations

THREE_D_UNAVAILABLE_MESSAGE = "3D Service temporarily unavailable"


class ThreeDServiceUnavailableError(RuntimeError):
    """Raised when Meshy/Tripo circuits are OPEN and no usable fallback remains."""

    def __init__(self, message: str = THREE_D_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(message or THREE_D_UNAVAILABLE_MESSAGE)


class RenderEngineError(RuntimeError):
    """Base error for the autonomous 3D render pipeline."""


class MeshLoadError(RenderEngineError):
    """Mesh bytes / path could not be decoded."""


class HeadlessGLError(RenderEngineError):
    """No usable offscreen GL context could be initialised."""


class FFmpegEncodeError(RenderEngineError):
    """FFmpeg subprocess failed or produced an empty container."""


__all__ = [
    "FFmpegEncodeError",
    "HeadlessGLError",
    "MeshLoadError",
    "RenderEngineError",
    "THREE_D_UNAVAILABLE_MESSAGE",
    "ThreeDServiceUnavailableError",
]
