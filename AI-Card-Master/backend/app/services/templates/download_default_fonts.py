"""Download default Cyrillic-capable TTFs into ``app/assets/fonts``.

Fetches OFL / Apache-licensed Google Fonts upstream files via the jsDelivr
CDN mirror of the official Google Fonts / upstream repos when they are missing
locally. Safe to call repeatedly (no-op when files already exist).
"""

from __future__ import annotations

import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_APP_ASSETS_FONTS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "assets" / "fonts"
)

# Legal Google Fonts upstream (OFL / Apache 2.0) via jsDelivr CDN.
DEFAULT_FONT_DOWNLOADS: Final[dict[str, str]] = {
    "Inter-Regular.ttf": (
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/inter/"
        "Inter%5Bopsz%2Cwght%5D.ttf"
    ),
    "Montserrat-Bold.ttf": (
        "https://cdn.jsdelivr.net/gh/JulietaUla/Montserrat@master/fonts/ttf/"
        "Montserrat-Bold.ttf"
    ),
    "Roboto-Regular.ttf": (
        "https://cdn.jsdelivr.net/gh/googlefonts/roboto@main/src/hinted/"
        "Roboto-Regular.ttf"
    ),
}

_TTF_MAGIC: Final[bytes] = b"\x00\x01\x00\x00"
_OTF_MAGIC: Final[bytes] = b"OTTO"
_USER_AGENT: Final[str] = (
    "AI-Card-Master/1.0 (+https://github.com/google/fonts; font bootstrap)"
)
_TIMEOUT_SECONDS: Final[float] = 60.0
_MAX_BYTES: Final[int] = 12 * 1024 * 1024

_lock = threading.Lock()
_ensured = False


def default_fonts_dir() -> Path:
    """Return the canonical ``app/assets/fonts`` directory."""

    return _APP_ASSETS_FONTS_DIR


def ensure_default_fonts(
    target_dir: Path | None = None,
    *,
    force: bool = False,
) -> list[Path]:
    """Ensure Inter / Montserrat / Roboto TTFs exist under ``target_dir``.

    Downloads only missing files (unless ``force=True``). Returns paths of
    fonts that were newly written. Concurrent callers share one bootstrap.
    """

    global _ensured
    dest = Path(target_dir) if target_dir is not None else _APP_ASSETS_FONTS_DIR
    with _lock:
        if _ensured and not force:
            existing = [
                dest / name
                for name in DEFAULT_FONT_DOWNLOADS
                if (dest / name).is_file()
            ]
            if len(existing) == len(DEFAULT_FONT_DOWNLOADS):
                return []
        written = _download_missing(dest, force=force)
        _ensured = True
        return written


def _download_missing(dest: Path, *, force: bool) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, url in DEFAULT_FONT_DOWNLOADS.items():
        path = dest / filename
        if path.is_file() and path.stat().st_size > 1024 and not force:
            logger.debug("Default font already present: %s", path)
            continue
        try:
            payload = _fetch_font_bytes(url)
            _validate_sfnt(payload, filename=filename)
            tmp = path.with_suffix(path.suffix + ".partial")
            tmp.write_bytes(payload)
            tmp.replace(path)
            written.append(path)
            logger.info(
                "Downloaded default Cyrillic font %s (%s bytes) from Google Fonts CDN",
                filename,
                len(payload),
            )
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning(
                "Failed to download default font %s from %s: %s",
                filename,
                url,
                exc,
            )
    return written


def _fetch_font_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ValueError(f"Font download exceeded {_MAX_BYTES} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def _validate_sfnt(payload: bytes, *, filename: str) -> None:
    if len(payload) < 16:
        raise ValueError(f"{filename}: download too small ({len(payload)} bytes)")
    magic = payload[:4]
    if magic not in {_TTF_MAGIC, _OTF_MAGIC, b"true", b"typ1"}:
        raise ValueError(
            f"{filename}: not a TrueType/OpenType font (magic={magic!r})"
        )


__all__ = [
    "DEFAULT_FONT_DOWNLOADS",
    "default_fonts_dir",
    "ensure_default_fonts",
]
