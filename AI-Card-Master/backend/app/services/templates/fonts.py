"""In-memory FontRegistry for server-side canvas text rendering.

Loads ``.ttf`` files once and caches FreeType font objects keyed by
``(family, weight, size)``. Custom font paths (from ``custom_fonts`` DB rows)
can be registered at runtime without restarting the process.
"""

from __future__ import annotations

import logging
import threading
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import ImageFont

logger = logging.getLogger(__name__)

# Bundled / discoverable font roots (relative to this package and app root).
_PACKAGE_FONTS_DIR: Final[Path] = Path(__file__).resolve().parent / "font_files"
_APP_ASSETS_FONTS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "assets" / "fonts"
)

# Common system font locations (Windows / Linux / macOS).
_SYSTEM_FONT_DIRS: Final[tuple[Path, ...]] = (
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts"),
    Path("/usr/share/fonts/truetype"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/local/share/fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
)

# Canonical family → preferred filenames by weight bucket.
_FAMILY_FILES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "dejavusans": {
        "regular": ("DejaVuSans.ttf",),
        "bold": ("DejaVuSans-Bold.ttf",),
        "light": ("DejaVuSans.ttf",),
        "medium": ("DejaVuSans.ttf",),
        "semibold": ("DejaVuSans-Bold.ttf",),
        "black": ("DejaVuSans-Bold.ttf",),
    },
    "arial": {
        "regular": ("arial.ttf", "Arial.ttf", "Arial.ttf"),
        "bold": ("arialbd.ttf", "Arial Bold.ttf", "Arial-Bold.ttf"),
        "light": ("arial.ttf", "Arial.ttf"),
        "medium": ("arial.ttf", "Arial.ttf"),
        "semibold": ("arialbd.ttf", "Arial Bold.ttf"),
        "black": ("ariblk.ttf", "Arial Black.ttf", "arialbd.ttf"),
    },
    "helvetica": {
        "regular": ("Helvetica.ttc", "Arial.ttf", "arial.ttf", "DejaVuSans.ttf"),
        "bold": (
            "Helvetica-Bold.ttf",
            "Arial Bold.ttf",
            "arialbd.ttf",
            "DejaVuSans-Bold.ttf",
        ),
        "light": ("Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf"),
        "medium": ("Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf"),
        "semibold": ("Helvetica-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
        "black": ("Helvetica-Bold.ttf", "ariblk.ttf", "DejaVuSans-Bold.ttf"),
    },
    "inter": {
        "regular": ("Inter-Regular.ttf", "Inter.ttf", "DejaVuSans.ttf"),
        "bold": ("Inter-Bold.ttf", "Inter-Regular.ttf", "DejaVuSans-Bold.ttf"),
        "light": ("Inter-Light.ttf", "Inter-Regular.ttf", "DejaVuSans.ttf"),
        "medium": ("Inter-Medium.ttf", "Inter-Regular.ttf", "DejaVuSans.ttf"),
        "semibold": ("Inter-SemiBold.ttf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf"),
        "extrabold": (
            "Inter-ExtraBold.ttf",
            "Inter-Bold.ttf",
            "Inter-Black.ttf",
            "DejaVuSans-Bold.ttf",
        ),
        "black": ("Inter-Black.ttf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf"),
    },
    "montserrat": {
        "regular": ("Montserrat-Regular.ttf", "Montserrat.ttf", "DejaVuSans.ttf"),
        "bold": ("Montserrat-Bold.ttf", "Montserrat-Regular.ttf", "DejaVuSans-Bold.ttf"),
        "light": ("Montserrat-Light.ttf", "Montserrat-Regular.ttf", "DejaVuSans.ttf"),
        "medium": ("Montserrat-Medium.ttf", "Montserrat-Regular.ttf", "DejaVuSans.ttf"),
        "semibold": (
            "Montserrat-SemiBold.ttf",
            "Montserrat-Bold.ttf",
            "DejaVuSans-Bold.ttf",
        ),
        "black": ("Montserrat-Black.ttf", "Montserrat-Bold.ttf", "DejaVuSans-Bold.ttf"),
    },
    "roboto": {
        "regular": ("Roboto-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"),
        "bold": ("Roboto-Bold.ttf", "Roboto-Regular.ttf", "DejaVuSans-Bold.ttf"),
        "light": ("Roboto-Light.ttf", "Roboto-Regular.ttf", "DejaVuSans.ttf"),
        "medium": ("Roboto-Medium.ttf", "Roboto-Regular.ttf", "DejaVuSans.ttf"),
        "semibold": ("Roboto-Medium.ttf", "Roboto-Bold.ttf", "arialbd.ttf"),
        "black": ("Roboto-Black.ttf", "Roboto-Bold.ttf", "DejaVuSans-Bold.ttf"),
    },
    "oswald": {
        "regular": ("Oswald-Regular.ttf", "Oswald.ttf", "DejaVuSans.ttf"),
        "bold": ("Oswald-Bold.ttf", "DejaVuSans-Bold.ttf"),
        "light": ("Oswald-Light.ttf", "Oswald-Regular.ttf", "DejaVuSans.ttf"),
        "medium": ("Oswald-Medium.ttf", "Oswald-Regular.ttf", "DejaVuSans.ttf"),
        "semibold": ("Oswald-SemiBold.ttf", "Oswald-Bold.ttf", "DejaVuSans-Bold.ttf"),
        "black": ("Oswald-Bold.ttf", "DejaVuSans-Bold.ttf"),
    },
    "bebas neue": {
        "regular": (
            "BebasNeue-Regular.ttf",
            "BebasNeue.ttf",
            "BebasNeue-Regular.otf",
            "DejaVuSans.ttf",
        ),
        "bold": ("BebasNeue-Bold.ttf", "BebasNeue.ttf", "DejaVuSans-Bold.ttf"),
        "light": ("BebasNeue-Light.ttf", "BebasNeue-Regular.ttf", "DejaVuSans.ttf"),
        "medium": ("BebasNeue-Regular.ttf", "BebasNeue.ttf", "DejaVuSans.ttf"),
        "semibold": ("BebasNeue-Bold.ttf", "BebasNeue.ttf", "DejaVuSans-Bold.ttf"),
        "black": ("BebasNeue-Bold.ttf", "BebasNeue.ttf", "DejaVuSans-Bold.ttf"),
    },
    "times new roman": {
        "regular": ("times.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf"),
        "bold": ("timesbd.ttf", "Times New Roman Bold.ttf", "DejaVuSerif-Bold.ttf"),
        "light": ("times.ttf", "DejaVuSerif.ttf"),
        "medium": ("times.ttf", "DejaVuSerif.ttf"),
        "semibold": ("timesbd.ttf", "DejaVuSerif-Bold.ttf"),
        "black": ("timesbd.ttf", "DejaVuSerif-Bold.ttf"),
    },
    "dejavuserif": {
        "regular": ("DejaVuSerif.ttf",),
        "bold": ("DejaVuSerif-Bold.ttf",),
        "light": ("DejaVuSerif.ttf",),
        "medium": ("DejaVuSerif.ttf",),
        "semibold": ("DejaVuSerif-Bold.ttf",),
        "black": ("DejaVuSerif-Bold.ttf",),
    },
}

_WEIGHT_ALIASES: Final[dict[str, str]] = {
    "100": "light",
    "200": "light",
    "300": "light",
    "400": "regular",
    "normal": "regular",
    "regular": "regular",
    "500": "medium",
    "medium": "medium",
    "600": "semibold",
    "semibold": "semibold",
    "demi": "semibold",
    "demibold": "semibold",
    "700": "bold",
    "bold": "bold",
    "800": "extrabold",
    "extrabold": "extrabold",
    "ultrabold": "extrabold",
    "900": "black",
    "black": "black",
    "heavy": "black",
}

# Variable-font weight axis values (wght) for Inter / similar VF masters.
_WEIGHT_AXIS_VALUES: Final[dict[str, int]] = {
    "light": 300,
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "extrabold": 800,
    "black": 900,
}


class FontRegistry:
    """Process-wide cache of TTF bytes and Pillow ``FreeTypeFont`` instances."""

    def __init__(self, *, extra_search_dirs: list[Path] | None = None) -> None:
        self._lock = threading.RLock()
        # Absolute path → raw TTF/OTF bytes (loaded once).
        self._file_bytes: dict[str, bytes] = {}
        # (resolved_path, size_px, weight_bucket) → FreeType font instance
        self._font_objects: dict[
            tuple[str, int, str], ImageFont.FreeTypeFont
        ] = {}
        # (normalized_family, weight_bucket) → absolute path
        self._family_index: dict[tuple[str, str], str] = {}
        self._search_dirs: list[Path] = [
            _PACKAGE_FONTS_DIR,
            _APP_ASSETS_FONTS_DIR,
            *(_SYSTEM_FONT_DIRS),
        ]
        if extra_search_dirs:
            self._search_dirs.extend(extra_search_dirs)

    def register_file(
        self,
        *,
        font_family: str,
        file_path_ttf: str | Path,
        font_weight: str = "regular",
    ) -> Path:
        """Register a custom TTF path for a family/weight (e. and from DB)."""

        path = Path(file_path_ttf).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Font file not found: {path}")

        family_key = _normalize_family(font_family)
        weight_key = _normalize_weight(font_weight)
        with self._lock:
            self._family_index[(family_key, weight_key)] = str(path)
            # Eagerly warm the byte cache.
            self._load_bytes_unlocked(path)
        return path

    def get_font(
        self,
        font_family: str,
        font_size: int,
        font_weight: str = "regular",
    ) -> ImageFont.FreeTypeFont:
        """Resolve and return a cached Pillow FreeType font for the given style.

        Always returns ``ImageFont.truetype`` — never Pillow's bitmap
        ``load_default()``, which cannot render Cyrillic (tofu □□□).
        Missing default families trigger an automatic CDN download into
        ``app/assets/fonts`` before a second resolution pass.
        """

        size = max(1, int(font_size))
        path = self.resolve_path(font_family, font_weight)
        if path is None:
            path = self._ensure_defaults_and_resolve(font_family, font_weight)
        if path is None:
            # Last Unicode-capable system fallbacks (still TrueType).
            for fallback_family, fallback_weight in (
                ("Inter", font_weight),
                ("Inter", "regular"),
                ("DejaVuSans", font_weight),
                ("DejaVuSans", "regular"),
                ("Arial", font_weight),
                ("Arial", "regular"),
            ):
                path = self.resolve_path(fallback_family, fallback_weight)
                if path is not None:
                    logger.warning(
                        "Font family=%s weight=%s missing; using %s/%s at %s",
                        font_family,
                        font_weight,
                        fallback_family,
                        fallback_weight,
                        path,
                    )
                    break
        if path is None:
            raise FileNotFoundError(
                f"No TrueType font available for family={font_family!r} "
                f"weight={font_weight!r}. Place Inter/Montserrat/Roboto under "
                f"{_APP_ASSETS_FONTS_DIR} or allow CDN bootstrap."
            )

        key = (str(path), size, _normalize_weight(font_weight))
        with self._lock:
            cached = self._font_objects.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]
            payload = self._load_bytes_unlocked(path)
            font = ImageFont.truetype(font=BytesIO(payload), size=size)
            _apply_variable_weight(font, _normalize_weight(font_weight))
            self._font_objects[key] = font
            return font

    def _ensure_defaults_and_resolve(
        self,
        font_family: str,
        font_weight: str,
    ) -> Path | None:
        """Download default Cyrillic TTFs when a requested family is missing."""

        try:
            from app.services.templates.download_default_fonts import (
                ensure_default_fonts,
            )

            written = ensure_default_fonts(_APP_ASSETS_FONTS_DIR)
            if written:
                logger.info(
                    "Auto-downloaded %s font file(s) before canvas render",
                    len(written),
                )
                # Drop path memoisation so newly written files are discoverable.
                with self._lock:
                    stale = [
                        key
                        for key in self._family_index
                        if key[0] == _normalize_family(font_family)
                    ]
                    for key in stale:
                        self._family_index.pop(key, None)
        except Exception:
            logger.exception("Auto-download of default fonts failed")
        return self.resolve_path(font_family, font_weight)

    def resolve_path(
        self,
        font_family: str,
        font_weight: str = "regular",
    ) -> Path | None:
        """Locate a TTF/OTF path for family+weight without instantiating a font."""

        family_key = _normalize_family(font_family)
        weight_key = _normalize_weight(font_weight)

        with self._lock:
            indexed = self._family_index.get((family_key, weight_key))
            if indexed:
                return Path(indexed)
            # Fall back to regular weight of the same family.
            if weight_key != "regular":
                indexed = self._family_index.get((family_key, "regular"))
                if indexed:
                    return Path(indexed)

        candidates = self._candidate_filenames(family_key, weight_key)
        for directory in self._search_dirs:
            if not directory.exists():
                continue
            for name in candidates:
                path = directory / name
                if path.is_file():
                    with self._lock:
                        self._family_index[(family_key, weight_key)] = str(path.resolve())
                    return path.resolve()
            # Recursive shallow search for exact filename matches.
            for name in candidates:
                matches = list(directory.rglob(name))
                for match in matches:
                    if match.is_file():
                        with self._lock:
                            self._family_index[(family_key, weight_key)] = str(
                                match.resolve()
                            )
                        return match.resolve()

        return None

    def has_family(self, font_family: str) -> bool:
        """True when the family is explicitly indexed or has a dedicated file.

        Unlike ``resolve_path``, this does **not** treat universal DejaVu/Arial
        fallbacks as a successful family match — missing custom names stay missing.
        """

        family_key = _normalize_family(font_family)
        with self._lock:
            if any(key[0] == family_key for key in self._family_index):
                return True

        # Known mapped families: accept when any weight file is discoverable
        # without the universal Unicode fallbacks.
        mapped = _FAMILY_FILES.get(family_key)
        search_names: list[str] = []
        if mapped:
            for names in mapped.values():
                for name in names:
                    lower = name.lower()
                    if lower.startswith(("dejavu", "arial", "times")):
                        continue
                    search_names.append(name)
        else:
            pretty = font_family_title(family_key)
            compact = pretty.replace(" ", "")
            search_names.extend(
                (
                    f"{pretty}.ttf",
                    f"{compact}.ttf",
                    f"{pretty}-Regular.ttf",
                    f"{compact}-Regular.ttf",
                    f"{pretty}.otf",
                    f"{compact}.otf",
                    f"{pretty}-Regular.otf",
                    f"{compact}-Regular.otf",
                )
            )

        for directory in self._search_dirs:
            if not directory.exists():
                continue
            for name in search_names:
                path = directory / name
                if path.is_file():
                    return True
                for match in directory.rglob(name):
                    if match.is_file():
                        return True
        return False

    def clear_cache(self) -> None:
        """Drop in-memory font bytes and FreeType instances (keeps path index)."""

        with self._lock:
            self._file_bytes.clear()
            self._font_objects.clear()

    @property
    def cached_font_count(self) -> int:
        with self._lock:
            return len(self._font_objects)

    @property
    def cached_file_count(self) -> int:
        with self._lock:
            return len(self._file_bytes)

    def _load_bytes_unlocked(self, path: Path) -> bytes:
        key = str(path.resolve())
        cached = self._file_bytes.get(key)
        if cached is not None:
            return cached
        payload = path.read_bytes()
        if not payload:
            raise OSError(f"Font file is empty: {path}")
        self._file_bytes[key] = payload
        return payload

    def _candidate_filenames(
        self,
        family_key: str,
        weight_key: str,
    ) -> tuple[str, ...]:
        mapped = _FAMILY_FILES.get(family_key, {}).get(weight_key)
        if mapped:
            return mapped

        # Generic heuristics: Family-Bold.ttf, Family.ttf, etc.
        pretty = font_family_title(family_key)
        compact = pretty.replace(" ", "")
        weight_suffix = {
            "regular": ("", "-Regular", " Regular"),
            "bold": ("-Bold", " Bold", "bd", "-Bold"),
            "light": ("-Light", " Light"),
            "medium": ("-Medium", " Medium"),
            "semibold": ("-SemiBold", "-Semibold", " SemiBold"),
            "extrabold": ("-ExtraBold", "-Extrabold", "-Bold", "-Black"),
            "black": ("-Black", " Black", "blk"),
        }.get(weight_key, ("",))

        names: list[str] = []
        for suffix in weight_suffix:
            names.append(f"{pretty}{suffix}.ttf")
            names.append(f"{compact}{suffix}.ttf")
            names.append(f"{pretty}{suffix}.otf")
            names.append(f"{compact}{suffix}.otf")
        if weight_key == "regular":
            names.extend(
                (
                    f"{pretty}.ttf",
                    f"{compact}.ttf",
                    f"{pretty}.otf",
                    f"{compact}.otf",
                )
            )
        # Always end with DejaVu as universal Unicode-capable fallback.
        names.extend(("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"))
        # Preserve order, drop duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return tuple(ordered)


_GLOBAL_REGISTRY: FontRegistry | None = None
_GLOBAL_LOCK = threading.Lock()


def get_font_registry() -> FontRegistry:
    """Return the process-singleton FontRegistry (lazy init)."""

    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is not None:
        return _GLOBAL_REGISTRY
    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = FontRegistry()
        return _GLOBAL_REGISTRY


def normalize_font_family(font_family: str) -> str:
    """Public helper: lowercase / collapse whitespace for family keys."""

    return _normalize_family(font_family)


def normalize_font_weight(font_weight: str) -> str:
    """Public helper: map CSS / numeric weights onto registry buckets."""

    return _normalize_weight(font_weight)


def _apply_variable_weight(font: ImageFont.FreeTypeFont, weight_key: str) -> None:
    """Select Bold/Medium/etc. on variable TTFs (e.g. Inter opsz+wght)."""

    target = _WEIGHT_AXIS_VALUES.get(weight_key)
    if target is None:
        return
    try:
        axes = font.get_variation_axes()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — non-variable fonts raise here
        return
    if not axes:
        return

    values: list[float] = []
    for axis in axes:
        name = axis.get("name", b"")
        if isinstance(name, bytes):
            name_l = name.decode("ascii", errors="ignore").lower()
        else:
            name_l = str(name).lower()
        default = float(axis.get("default", 400))
        if "weight" in name_l or name_l == "wght":
            values.append(float(target))
        else:
            values.append(default)
    try:
        font.set_variation_by_axes(values)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        logger.debug("Variable font weight axis apply failed", exc_info=True)


def _normalize_family(font_family: str) -> str:
    return " ".join(font_family.strip().lower().replace("_", " ").split())


def _normalize_weight(font_weight: str) -> str:
    key = font_weight.strip().lower().replace(" ", "")
    return _WEIGHT_ALIASES.get(key, "regular")


def font_family_title(family_key: str) -> str:
    return " ".join(part.capitalize() for part in family_key.split())
