"""Rembg / ONNX background removal engine."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from typing import Final

from PIL import Image

from app.services.bg_removal.dto import BgRemovalResultDTO

RemoverFn = Callable[[bytes], bytes]

MAX_IMAGE_PIXELS: Final[int] = 40_000_000


class BackgroundRemovalEngineError(ValueError):
    """Raised when rembg / image decoding fails."""


def remove_background(image_bytes: bytes) -> bytes:
    """Remove the product background and return a PNG with alpha.

    Uses the rembg ONNX session (u2net by default). Pure sync helper so callers
    can run it via ``asyncio.to_thread``.
    """

    payload = bytes(image_bytes or b"")
    if not payload:
        raise BackgroundRemovalEngineError("image_bytes must not be empty.")

    try:
        from rembg import remove as rembg_remove
    except ImportError as exc:  # pragma: no cover - env without rembg
        raise BackgroundRemovalEngineError(
            "rembg is not installed. Add rembg to requirements and install it."
        ) from exc

    try:
        with Image.open(io.BytesIO(payload)) as probe:
            probe.load()
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                raise BackgroundRemovalEngineError(
                    f"Image exceeds the {MAX_IMAGE_PIXELS}-pixel safety limit."
                )
    except BackgroundRemovalEngineError:
        raise
    except Exception as exc:
        raise BackgroundRemovalEngineError(
            f"Invalid or unsupported image: {exc}"
        ) from exc

    try:
        output = rembg_remove(payload)
    except Exception as exc:
        raise BackgroundRemovalEngineError(
            f"Background removal failed: {exc}"
        ) from exc

    if not output:
        raise BackgroundRemovalEngineError("rembg returned an empty result.")

    # Ensure we always hand out a real PNG with an alpha channel.
    try:
        with Image.open(io.BytesIO(output)) as cutout:
            cutout.load()
            rgba = cutout.convert("RGBA")
            buffer = io.BytesIO()
            rgba.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as exc:
        raise BackgroundRemovalEngineError(
            f"Failed to encode cutout PNG: {exc}"
        ) from exc


class BackgroundRemovalEngine:
    """Async facade over ``remove_background`` (CPU / ONNX off the event loop)."""

    def __init__(self, *, remover: RemoverFn | None = None) -> None:
        self._remover: RemoverFn = remover or remove_background

    async def process(self, image_bytes: bytes) -> BgRemovalResultDTO:
        png_bytes = await asyncio.to_thread(self._remover, bytes(image_bytes))
        if not png_bytes:
            raise BackgroundRemovalEngineError("Background removal returned empty bytes.")

        try:
            with Image.open(io.BytesIO(png_bytes)) as image:
                image.load()
                width, height = image.size
                if image.mode != "RGBA":
                    # Caller-injected removers should still produce PNG; normalize.
                    buffer = io.BytesIO()
                    image.convert("RGBA").save(buffer, format="PNG")
                    png_bytes = buffer.getvalue()
        except Exception as exc:
            raise BackgroundRemovalEngineError(
                f"Cutout is not a valid image: {exc}"
            ) from exc

        if width <= 0 or height <= 0:
            raise BackgroundRemovalEngineError("Cutout has invalid dimensions.")

        return BgRemovalResultDTO(
            image_png=png_bytes,
            width=int(width),
            height=int(height),
        )
