"""Normalize competitor images for Claude Opus 4.7 Vision limits."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

# Opus 4.7 raises the long-edge cap to 2576px; keep a small safety margin.
_MAX_LONG_EDGE = 2576
_MAX_PIXELS = 3_750_000


def normalize_image_for_claude(
    data: bytes,
    *,
    media_type: str,
) -> tuple[bytes, str]:
    """Downscale oversized images while preserving format when possible."""

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            long_edge = max(width, height)
            pixels = width * height
            if long_edge <= _MAX_LONG_EDGE and pixels <= _MAX_PIXELS:
                return data, media_type

            scale = min(
                _MAX_LONG_EDGE / float(long_edge),
                (_MAX_PIXELS / float(pixels)) ** 0.5,
            )
            new_size = (
                max(1, int(width * scale)),
                max(1, int(height * scale)),
            )
            resized = image.resize(new_size, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            if media_type == "image/png":
                resized.save(buffer, format="PNG", optimize=True)
                return buffer.getvalue(), "image/png"
            if media_type == "image/webp":
                resized.save(buffer, format="WEBP", quality=90, method=4)
                return buffer.getvalue(), "image/webp"
            if resized.mode not in ("RGB", "L"):
                resized = resized.convert("RGB")
            resized.save(buffer, format="JPEG", quality=90, optimize=True)
            return buffer.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError, ValueError):
        return data, media_type
