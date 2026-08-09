"""Pure image validation for generation uploads (no FastAPI dependency)."""

from __future__ import annotations

import asyncio
import io

from PIL import Image, UnidentifiedImageError

from app.application.generation_errors import (
    GenerationBadRequestError,
    GenerationPayloadTooLargeError,
    GenerationUnsupportedMediaError,
    GenerationValidationError,
)

_MIME_BY_SIGNATURE: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


_MIME_ALIASES: dict[str, str] = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}


def _normalize_claimed_content_type(claimed: str | None) -> str | None:
    if not claimed:
        return None
    base = claimed.split(";", 1)[0].strip().lower()
    if not base:
        return None
    return _MIME_ALIASES.get(base, base)


def read_bounded_bytes(data: bytes, *, max_bytes: int) -> bytes:
    """Validate an already-buffered payload against size limits."""

    if not data:
        raise GenerationBadRequestError("Uploaded image is empty.")
    if len(data) > max_bytes:
        raise GenerationPayloadTooLargeError(
            f"Image exceeds the {max_bytes}-byte upload limit."
        )
    return data


async def validate_image(
    data: bytes,
    claimed_content_type: str | None,
) -> tuple[str, str]:
    """Return ``(mime_type, extension)`` after magic-byte + PIL checks."""

    mime_type: str | None = None
    extension: str | None = None
    for signature, candidate_mime, candidate_extension in _MIME_BY_SIGNATURE:
        if data.startswith(signature):
            mime_type, extension = candidate_mime, candidate_extension
            break
    if (
        mime_type is None
        and len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        mime_type, extension = "image/webp", ".webp"
    if mime_type is None or extension is None:
        raise GenerationUnsupportedMediaError(
            "Unsupported image signature. Allowed: JPEG, PNG, WebP."
        )
    normalized_claim = _normalize_claimed_content_type(claimed_content_type)
    if normalized_claim and normalized_claim != mime_type:
        raise GenerationUnsupportedMediaError(
            "Declared content type does not match image bytes."
        )

    def _verify() -> None:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()

    try:
        await asyncio.to_thread(_verify)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise GenerationValidationError(
            "Image is malformed or cannot be decoded."
        ) from exc
    return mime_type, extension
