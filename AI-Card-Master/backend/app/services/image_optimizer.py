"""Pixel-lossless image optimisation with hard verification guarantees."""

from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field


class ImageOptimizationError(ValueError):
    """Image cannot be decoded or safely optimised."""


class OptimizedImage(BaseModel):
    """Strict output contract including the actual media type and extension."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    image_bytes: bytes
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    extension: Literal[".png", ".jpg", ".webp"]
    original_size: int = Field(ge=1)
    optimized_size: int = Field(ge=1)
    pixel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    optimized: bool


async def optimize_image_lossless(image_bytes: bytes) -> OptimizedImage:
    """Optimise in a worker thread and reject any pixel-changing candidate."""

    if not image_bytes:
        raise ImageOptimizationError("Image payload cannot be empty.")
    return await asyncio.to_thread(_optimize_sync, bytes(image_bytes))


def detect_image_format(image_bytes: bytes) -> tuple[str, str]:
    """Detect supported format from magic bytes."""

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if (
        len(image_bytes) >= 12
        and image_bytes[:4] == b"RIFF"
        and image_bytes[8:12] == b"WEBP"
    ):
        return "image/webp", ".webp"
    raise ImageOptimizationError(
        "Unsupported image format; expected PNG, JPEG, or WebP."
    )


def _optimize_sync(image_bytes: bytes) -> OptimizedImage:
    mime_type, extension = detect_image_format(image_bytes)
    original_hash = _decoded_pixel_hash(image_bytes)
    candidate = image_bytes

    if mime_type == "image/png":
        candidate = _encode_png_lossless(image_bytes)
    elif mime_type == "image/webp":
        candidate = _encode_webp_lossless(image_bytes)
    elif mime_type == "image/jpeg":
        candidate = _strip_jpeg_metadata_lossless(image_bytes)

    accepted = candidate if len(candidate) < len(image_bytes) else image_bytes
    accepted_hash = _decoded_pixel_hash(accepted)
    if accepted_hash != original_hash:
        # The output invariant is stronger than an encoder's promise.
        accepted = image_bytes
        accepted_hash = original_hash

    return OptimizedImage(
        image_bytes=accepted,
        mime_type=mime_type,  # type: ignore[arg-type]
        extension=extension,  # type: ignore[arg-type]
        original_size=len(image_bytes),
        optimized_size=len(accepted),
        pixel_sha256=accepted_hash,
        optimized=accepted is not image_bytes and accepted != image_bytes,
    )


def _decoded_pixel_hash(image_bytes: bytes) -> str:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            rgba = image.convert("RGBA")
            digest = hashlib.sha256()
            digest.update(f"{rgba.width}x{rgba.height}".encode("ascii"))
            digest.update(rgba.tobytes())
            return digest.hexdigest()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageOptimizationError(
            "Image is malformed or cannot be decoded."
        ) from exc


def _encode_png_lossless(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as source:
        source.load()
        output = io.BytesIO()
        source.save(output, format="PNG", optimize=True, compress_level=9)
        return output.getvalue()


def _encode_webp_lossless(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as source:
        source.load()
        output = io.BytesIO()
        source.save(output, format="WEBP", lossless=True, quality=100, method=6)
        return output.getvalue()


def _strip_jpeg_metadata_lossless(image_bytes: bytes) -> bytes:
    """Remove EXIF/comment segments without touching JPEG entropy data."""

    if not image_bytes.startswith(b"\xff\xd8"):
        return image_bytes
    output = bytearray(image_bytes[:2])
    cursor = 2
    length = len(image_bytes)
    while cursor < length:
        if image_bytes[cursor] != 0xFF:
            return image_bytes
        marker_start = cursor
        while cursor < length and image_bytes[cursor] == 0xFF:
            cursor += 1
        if cursor >= length:
            return image_bytes
        marker = image_bytes[cursor]
        cursor += 1
        if marker == 0xDA:  # Start of scan: copy the compressed stream unchanged.
            output.extend(image_bytes[marker_start:])
            return bytes(output)
        if marker == 0xD9:
            output.extend(image_bytes[marker_start:cursor])
            return bytes(output)
        if marker in {0x01, *range(0xD0, 0xD8)}:
            output.extend(image_bytes[marker_start:cursor])
            continue
        if cursor + 2 > length:
            return image_bytes
        segment_length = int.from_bytes(image_bytes[cursor : cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > length:
            return image_bytes
        segment_end = cursor + segment_length
        # APP1 carries EXIF/XMP and COM carries plain comments. Keep ICC/APP2
        # because it can affect colour rendering.
        if marker not in {0xE1, 0xFE}:
            output.extend(image_bytes[marker_start:segment_end])
        cursor = segment_end
    return image_bytes
