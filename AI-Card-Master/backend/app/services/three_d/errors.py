"""Shared 3D engine errors surfaced to the API / workers."""

from __future__ import annotations

THREE_D_UNAVAILABLE_MESSAGE = "3D Service temporarily unavailable"


class ThreeDServiceUnavailableError(RuntimeError):
    """Raised when Meshy/Tripo circuits are OPEN and no usable fallback remains."""

    def __init__(self, message: str = THREE_D_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(message or THREE_D_UNAVAILABLE_MESSAGE)
