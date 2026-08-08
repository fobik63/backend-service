"""Rembg / ONNX background removal engine with alpha matting + edge cleanup."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from typing import Final

from PIL import Image

from app.services.bg_removal.dto import BgRemovalResultDTO
from app.services.bg_removal.postprocess import refine_cutout_rgba

RemoverFn = Callable[..., bytes]

MAX_IMAGE_PIXELS: Final[int] = 40_000_000

# rembg alpha-matting knobs (soft edge / hair / fabric silhouettes).
ALPHA_MATTING: Final[bool] = True
ALPHA_MATTING_FOREGROUND_THRESHOLD: Final[int] = 240
ALPHA_MATTING_BACKGROUND_THRESHOLD: Final[int] = 10
ALPHA_MATTING_ERODE_SIZE: Final[int] = 10


class BackgroundRemovalEngineError(ValueError):
    """Raised when rembg / image decoding fails."""


def remove_background(image_bytes: bytes) -> bytes:
    """Remove the product background and return a cleaned PNG with alpha.

    Pipeline:
    1. rembg ONNX (u2net) with alpha matting for soft contours
    2. morphological alpha erosion + light edge blur
    3. defringe — replace fringe RGB with nearest solid product colours
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
        output = rembg_remove(
            payload,
            alpha_matting=ALPHA_MATTING,
            alpha_matting_foreground_threshold=ALPHA_MATTING_FOREGROUND_THRESHOLD,
            alpha_matting_background_threshold=ALPHA_MATTING_BACKGROUND_THRESHOLD,
            alpha_matting_erode_size=ALPHA_MATTING_ERODE_SIZE,
        )
    except Exception as exc:
        raise BackgroundRemovalEngineError(
            f"Background removal failed: {exc}"
        ) from exc

    if not output:
        raise BackgroundRemovalEngineError("rembg returned an empty result.")

    try:
        with Image.open(io.BytesIO(output)) as cutout:
            cutout.load()
            cleaned = refine_cutout_rgba(cutout.convert("RGBA"))
            buffer = io.BytesIO()
            cleaned.save(buffer, format="PNG")
            return buffer.getvalue()
    except BackgroundRemovalEngineError:
        raise
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
