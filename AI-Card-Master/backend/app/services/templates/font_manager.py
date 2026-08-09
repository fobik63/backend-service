"""Font asset manager: system registry, custom uploads, and template fallbacks.

``FontManagerService`` scans ``app/assets/fonts`` at startup for default
Cyrillic-capable families, accepts user ``.ttf`` / ``.otf`` uploads (signature
+ fontTools metadata), persists rows in ``custom_fonts``, and resolves missing
template font families to Inter with a warning log.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final, Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import CustomFont
from app.services.templates.fonts import (
    FontRegistry,
    font_family_title,
    get_font_registry,
    normalize_font_family,
)

logger = logging.getLogger(__name__)

# Default Cyrillic-capable families expected under assets/fonts/.
DEFAULT_SYSTEM_FAMILIES: Final[tuple[str, ...]] = (
    "Inter",
    "Montserrat",
    "Roboto",
    "Oswald",
    "Bebas Neue",
)

DEFAULT_FALLBACK_FAMILY: Final[str] = "Inter"

_PACKAGE_FONTS_DIR: Final[Path] = Path(__file__).resolve().parent / "font_files"
_APP_ASSETS_FONTS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "assets" / "fonts"
)
_LOCAL_CUSTOM_FONTS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[3] / "storage" / "fonts"
)

# TrueType / OpenType magic signatures (sfnt).
_TTF_OTF_SIGNATURES: Final[tuple[bytes, ...]] = (
    b"\x00\x01\x00\x00",  # TrueType
    b"OTTO",  # CFF OpenType
    b"true",  # Apple TrueType
    b"typ1",  # Type 1 sfnt
)

_MAX_FONT_UPLOAD_BYTES: Final[int] = 8 * 1024 * 1024  # 8 MiB
_ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({".ttf", ".otf"})
_CONTENT_TYPES: Final[dict[str, str]] = {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

_WEIGHT_FROM_STYLE: Final[dict[str, str]] = {
    "thin": "light",
    "extralight": "light",
    "ultralight": "light",
    "light": "light",
    "regular": "regular",
    "normal": "regular",
    "book": "regular",
    "roman": "regular",
    "medium": "medium",
    "semibold": "semibold",
    "demibold": "semibold",
    "bold": "bold",
    "extrabold": "black",
    "ultrabold": "black",
    "black": "black",
    "heavy": "black",
}


class FontManagerError(Exception):
    """Base font-manager failure."""


class FontValidationError(FontManagerError):
    """Uploaded bytes failed signature / metadata checks."""


class FontStorageError(FontManagerError):
    """Local or S3 persistence failed."""


@dataclass(frozen=True, slots=True)
class ParsedFontMetadata:
    """Name-table fields extracted via fontTools."""

    font_family: str
    font_name: str
    font_weight: str
    postscript_name: str | None
    extension: str  # ".ttf" | ".otf"


@dataclass(frozen=True, slots=True)
class UploadedFontResult:
    """Outcome of a successful custom font upload."""

    id: UUID
    font_name: str
    font_family: str
    file_path_ttf: str
    file_path_woff2: str | None
    is_system: bool
    storage: Literal["s3", "local"]
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FontResolveResult:
    """Resolved family after optional fallback."""

    requested_family: str
    resolved_family: str
    fell_back: bool


class FontManagerService:
    """Process-wide font asset registry and upload orchestrator."""

    def __init__(
        self,
        *,
        registry: FontRegistry | None = None,
        assets_dir: Path | None = None,
        custom_dir: Path | None = None,
        fallback_family: str = DEFAULT_FALLBACK_FAMILY,
    ) -> None:
        self._registry = registry or get_font_registry()
        self._assets_dir = assets_dir or _APP_ASSETS_FONTS_DIR
        self._package_dir = _PACKAGE_FONTS_DIR
        self._custom_dir = custom_dir or _LOCAL_CUSTOM_FONTS_DIR
        self._fallback_family = fallback_family
        self._lock = threading.RLock()
        # normalized family → set of known weight buckets / paths
        self._known_families: set[str] = set()
        self._bootstrapped = False

    @property
    def assets_dir(self) -> Path:
        return self._assets_dir

    @property
    def fallback_family(self) -> str:
        return self._fallback_family

    @property
    def known_families(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._known_families)

    def has_family(self, font_family: str) -> bool:
        """Return True when the family is registered or discoverable on disk."""

        family_key = normalize_font_family(font_family)
        with self._lock:
            if family_key in self._known_families:
                return True
        if self._registry.has_family(font_family):
            with self._lock:
                self._known_families.add(family_key)
            return True
        return False

    def resolve_family(self, font_family: str) -> FontResolveResult:
        """Resolve a template font family, falling back to Inter when missing."""

        requested = font_family.strip() or self._fallback_family
        if self.has_family(requested):
            return FontResolveResult(
                requested_family=requested,
                resolved_family=requested,
                fell_back=False,
            )

        logger.warning(
            "Font family %r is not registered; falling back to %r",
            requested,
            self._fallback_family,
        )
        # Ensure Inter / Montserrat / Roboto are on disk before rendering.
        if not self.has_family(self._fallback_family):
            try:
                from app.services.templates.download_default_fonts import (
                    ensure_default_fonts,
                )

                ensure_default_fonts(self._assets_dir)
                self._scan_and_register_system_fonts()
            except Exception:
                logger.exception(
                    "Failed to auto-download fallback font family %r",
                    self._fallback_family,
                )
        if not self.has_family(self._fallback_family):
            logger.error(
                "Fallback font family %r is unavailable after CDN bootstrap; "
                "canvas rendering will raise if no TrueType file can be resolved",
                self._fallback_family,
            )
        return FontResolveResult(
            requested_family=requested,
            resolved_family=self._fallback_family,
            fell_back=True,
        )

    def resolve_canvas_font_families(
        self,
        canvas_data: dict[str, object] | object,
    ) -> list[FontResolveResult]:
        """Walk canvas JSON / DTO layers and resolve every text ``font_family``."""

        layers: list[object]
        if isinstance(canvas_data, dict):
            raw_layers = canvas_data.get("layers", [])
            layers = list(raw_layers) if isinstance(raw_layers, list) else []
        else:
            layers = list(getattr(canvas_data, "layers", []) or [])

        results: list[FontResolveResult] = []
        for layer in layers:
            family = _extract_layer_font_family(layer)
            if family is None:
                continue
            results.append(self.resolve_family(family))
        return results

    async def bootstrap(self, *, persist_system_fonts: bool = True) -> int:
        """Scan system font folders, register defaults, optionally sync DB.

        Safe to call multiple times; subsequent calls are no-ops for scanning
        but still refresh the in-memory known-family set from the registry.
        """

        # Auto-fetch Inter / Montserrat / Roboto into assets/fonts when missing.
        try:
            from app.services.templates.download_default_fonts import (
                ensure_default_fonts,
            )

            downloaded = await asyncio.to_thread(
                ensure_default_fonts, self._assets_dir
            )
            if downloaded:
                logger.info(
                    "Downloaded %s default Cyrillic font file(s) into %s",
                    len(downloaded),
                    self._assets_dir,
                )
        except Exception:
            logger.exception(
                "Default font download helper failed; continuing with local assets"
            )

        registered = await asyncio.to_thread(self._scan_and_register_system_fonts)
        if persist_system_fonts:
            try:
                await self._persist_system_fonts_to_db()
            except Exception:
                logger.exception(
                    "Failed to persist system fonts into custom_fonts "
                    "(continuing with in-memory registry)"
                )
        self._bootstrapped = True
        logger.info(
            "FontManager bootstrap complete: %s system file(s) registered, "
            "known_families=%s",
            registered,
            sorted(self.known_families),
        )
        return registered

    def _scan_and_register_system_fonts(self) -> int:
        """Discover default families under assets/fonts and package font_files."""

        self._custom_dir.mkdir(parents=True, exist_ok=True)
        self._assets_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        search_roots = (self._assets_dir, self._package_dir)
        for family in DEFAULT_SYSTEM_FAMILIES:
            family_key = normalize_font_family(family)
            found_any = False
            for root in search_roots:
                if not root.exists():
                    continue
                matches = _find_family_files(root, family)
                for path, weight in matches:
                    try:
                        self._registry.register_file(
                            font_family=family,
                            file_path_ttf=path,
                            font_weight=weight,
                        )
                        count += 1
                        found_any = True
                        logger.info(
                            "Registered system font family=%s weight=%s path=%s",
                            family,
                            weight,
                            path,
                        )
                    except (OSError, FileNotFoundError) as exc:
                        logger.warning(
                            "Skipping unreadable font %s: %s", path, exc
                        )
            if found_any:
                with self._lock:
                    self._known_families.add(family_key)
            else:
                # Still mark as known if FontRegistry can resolve via OS dirs.
                if self._registry.has_family(family):
                    with self._lock:
                        self._known_families.add(family_key)
                    logger.info(
                        "System font family %r resolved via FontRegistry search paths",
                        family,
                    )
                else:
                    logger.warning(
                        "Default Cyrillic font family %r not found under %s "
                        "or %s — place .ttf/.otf files there for server rendering",
                        family,
                        self._assets_dir,
                        self._package_dir,
                    )
        return count

    async def _persist_system_fonts_to_db(self) -> None:
        """Upsert discovered default families into ``custom_fonts`` (is_system)."""

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.database import SessionLocal

        rows: list[dict[str, object]] = []
        for family in DEFAULT_SYSTEM_FAMILIES:
            path = self._registry.resolve_path(family, "regular")
            if path is None:
                continue
            rows.append(
                {
                    "font_name": f"{family}-Regular",
                    "font_family": family,
                    "file_path_ttf": str(path),
                    "file_path_woff2": None,
                    "is_system": True,
                }
            )
        if not rows:
            return

        async with SessionLocal() as session:
            stmt = pg_insert(CustomFont).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_custom_fonts_font_name",
                set_={
                    "font_family": stmt.excluded.font_family,
                    "file_path_ttf": stmt.excluded.file_path_ttf,
                    "is_system": True,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def load_custom_fonts_from_db(self, session: AsyncSession) -> int:
        """Register non-system custom font rows that point at local files."""

        from sqlalchemy import select

        result = await session.execute(
            select(CustomFont).where(CustomFont.is_system.is_(False))
        )
        fonts = list(result.scalars().all())
        loaded = 0
        for row in fonts:
            if not row.file_path_ttf:
                continue
            path = Path(row.file_path_ttf)
            if not await asyncio.to_thread(path.is_file):
                logger.warning(
                    "custom_fonts row %s path missing on disk: %s",
                    row.id,
                    row.file_path_ttf,
                )
                continue
            try:
                self._registry.register_file(
                    font_family=row.font_family,
                    file_path_ttf=path,
                    font_weight="regular",
                )
                with self._lock:
                    self._known_families.add(normalize_font_family(row.font_family))
                loaded += 1
            except (OSError, FileNotFoundError) as exc:
                logger.warning("Failed to register custom font %s: %s", row.id, exc)
        return loaded

    async def upload_font(
        self,
        *,
        session: AsyncSession,
        data: bytes,
        filename: str | None,
        content_type: str | None = None,
    ) -> UploadedFontResult:
        """Validate, store (S3 or local), and persist a custom font upload."""

        from sqlalchemy.exc import IntegrityError

        if not data:
            raise FontValidationError("Uploaded font file is empty.")
        if len(data) > _MAX_FONT_UPLOAD_BYTES:
            raise FontValidationError(
                f"Font exceeds the {_MAX_FONT_UPLOAD_BYTES}-byte upload limit."
            )

        extension = _resolve_extension(filename, content_type, data)
        _assert_font_signature(data)

        metadata = await asyncio.to_thread(
            parse_font_metadata, data, extension=extension
        )
        stored = await self._store_font_bytes(
            data=data,
            extension=extension,
            font_family=metadata.font_family,
        )

        row = CustomFont(
            font_name=metadata.font_name,
            font_family=metadata.font_family,
            file_path_ttf=stored.local_path,
            file_path_woff2=stored.s3_uri,
            is_system=False,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            try:
                await asyncio.to_thread(
                    Path(stored.local_path).unlink,
                    missing_ok=True,
                )
            except OSError:
                pass
            raise FontValidationError(
                f"Font name {metadata.font_name!r} is already registered."
            ) from exc
        except Exception:
            await session.rollback()
            try:
                await asyncio.to_thread(
                    Path(stored.local_path).unlink,
                    missing_ok=True,
                )
            except OSError:
                pass
            raise
        await session.refresh(row)

        self._registry.register_file(
            font_family=metadata.font_family,
            file_path_ttf=stored.local_path,
            font_weight=metadata.font_weight,
        )
        with self._lock:
            self._known_families.add(normalize_font_family(metadata.font_family))

        logger.info(
            "Custom font uploaded id=%s family=%s name=%s storage=%s",
            row.id,
            row.font_family,
            row.font_name,
            stored.backend,
        )
        return UploadedFontResult(
            id=row.id,
            font_name=row.font_name,
            font_family=row.font_family,
            file_path_ttf=row.file_path_ttf or stored.local_path,
            file_path_woff2=row.file_path_woff2,
            is_system=False,
            storage=stored.backend,
            size_bytes=len(data),
        )

    async def _store_font_bytes(
        self,
        *,
        data: bytes,
        extension: str,
        font_family: str,
    ) -> "_StoredFontPaths":
        self._custom_dir.mkdir(parents=True, exist_ok=True)
        file_id = uuid4().hex
        safe_family = re.sub(r"[^a-zA-Z0-9_-]+", "_", font_family)[:64] or "font"
        local_name = f"{safe_family}_{file_id}{extension}"
        local_path = self._custom_dir / local_name

        def _write_local() -> None:
            local_path.write_bytes(data)

        try:
            await asyncio.to_thread(_write_local)
        except OSError as exc:
            raise FontStorageError(f"Failed to write font to local storage: {exc}") from exc

        s3_uri: str | None = None
        backend: Literal["s3", "local"] = "local"
        try:
            from app.services.s3_storage import (
                S3StorageConfigurationError,
                S3StorageError,
                get_s3_storage,
            )

            storage = get_s3_storage()
            object_key = f"fonts/custom/{local_name}"
            content_type = _CONTENT_TYPES.get(extension, "application/octet-stream")
            uploaded = await storage.upload_bytes(
                object_key=object_key,
                data=data,
                content_type=content_type,
                presign=False,
                cache_control="public, max-age=31536000, immutable",
            )
            s3_uri = f"s3://{uploaded.bucket}/{uploaded.object_key}"
            backend = "s3"
        except S3StorageConfigurationError:
            logger.info("S3 not configured; custom font stored locally at %s", local_path)
        except S3StorageError as exc:
            logger.warning(
                "S3 upload failed for font %s; keeping local copy only: %s",
                local_path,
                exc,
            )
        except Exception:
            logger.exception(
                "Unexpected S3 error while uploading font; keeping local copy only"
            )

        return _StoredFontPaths(
            local_path=str(local_path.resolve()),
            s3_uri=s3_uri,
            backend=backend,
        )


@dataclass(frozen=True, slots=True)
class _StoredFontPaths:
    local_path: str
    s3_uri: str | None
    backend: Literal["s3", "local"]


def parse_font_metadata(data: bytes, *, extension: str) -> ParsedFontMetadata:
    """Parse family / full name / style via fontTools ``TTFont``."""

    try:
        from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - dependency must be installed
        raise FontValidationError(
            "fontTools is required to parse uploaded fonts. "
            "Install the backend requirements (fonttools)."
        ) from exc

    font = None
    family: str | None = None
    full_name: str | None = None
    style: str | None = None
    postscript: str | None = None
    try:
        try:
            font = TTFont(BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
        except Exception as exc:
            raise FontValidationError(f"Invalid font file: {exc}") from exc

        try:
            name_table = font["name"]
        except Exception as exc:
            raise FontValidationError(f"Font is missing the name table: {exc}") from exc

        family = _name_record(name_table, name_id=1) or _name_record(
            name_table, name_id=16
        )
        full_name = _name_record(name_table, name_id=4) or family
        style = _name_record(name_table, name_id=2) or "Regular"
        postscript = _name_record(name_table, name_id=6)
    finally:
        if font is not None:
            try:
                font.close()
            except Exception:
                logger.debug("TTFont.close() failed", exc_info=True)

    if not family or not family.strip():
        raise FontValidationError("Font metadata does not contain a family name.")

    family_clean = " ".join(family.strip().split())
    style_clean = " ".join(style.strip().split()) if style else "Regular"
    font_name = (full_name or f"{family_clean} {style_clean}").strip()
    font_name = " ".join(font_name.split())[:128]
    weight = _weight_from_style(style_clean)

    return ParsedFontMetadata(
        font_family=family_clean[:128],
        font_name=font_name,
        font_weight=weight,
        postscript_name=postscript,
        extension=extension,
    )


def _name_record(name_table: object, *, name_id: int) -> str | None:
    """Best-effort English (or first) name table string for ``name_id``."""

    get_name = getattr(name_table, "getDebugName", None)
    if callable(get_name):
        value = get_name(name_id)
        if isinstance(value, str) and value.strip():
            return value.strip()

    names = getattr(name_table, "names", None)
    if not names:
        return None
    preferred: str | None = None
    fallback: str | None = None
    for record in names:
        if getattr(record, "nameID", None) != name_id:
            continue
        try:
            text = record.toUnicode()
        except Exception:
            continue
        if not text or not str(text).strip():
            continue
        text = str(text).strip()
        lang = getattr(record, "langID", None)
        platform = getattr(record, "platformID", None)
        # Prefer Windows English (platform 3, lang 0x409).
        if platform == 3 and lang == 0x409:
            return text
        if preferred is None and platform in (1, 3):
            preferred = text
        if fallback is None:
            fallback = text
    return preferred or fallback


def _weight_from_style(style: str) -> str:
    key = style.lower().replace(" ", "").replace("-", "")
    for token, weight in _WEIGHT_FROM_STYLE.items():
        if token in key:
            return weight
    return "regular"


def _assert_font_signature(data: bytes) -> None:
    if len(data) < 4:
        raise FontValidationError("Font file is too small to be a valid TTF/OTF.")
    header = data[:4]
    if header not in _TTF_OTF_SIGNATURES:
        raise FontValidationError(
            "Invalid font signature. Only TrueType (.ttf) and OpenType (.otf) "
            "files are accepted."
        )


def _resolve_extension(
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> str:
    ext = ""
    if filename and "." in filename:
        ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        ctype = (content_type or "").lower().strip()
        if ctype in {"font/ttf", "application/x-font-ttf", "application/font-sfnt"}:
            ext = ".ttf"
        elif ctype in {"font/otf", "application/x-font-otf"}:
            ext = ".otf"
        elif data[:4] == b"OTTO":
            ext = ".otf"
        else:
            ext = ".ttf"
    if ext not in _ALLOWED_EXTENSIONS:
        raise FontValidationError(
            "Unsupported font extension. Allowed: .ttf, .otf."
        )
    return ext


def _find_family_files(root: Path, family: str) -> list[tuple[Path, str]]:
    """Locate TTF/OTF files whose stem matches a default family name."""

    family_key = normalize_font_family(family)
    compact = family_key.replace(" ", "")
    pretty = font_family_title(family_key).replace(" ", "")
    results: list[tuple[Path, str]] = []

    if not root.exists():
        return results

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue
        stem = path.stem.lower().replace("_", "").replace(" ", "")
        # Accept Inter.ttf, Inter-Regular.ttf, BebasNeue-Bold.otf, etc.
        if not (
            stem == compact
            or stem.startswith(compact)
            or stem.startswith(pretty.lower())
        ):
            # Also allow "bebasneue" for "Bebas Neue"
            if compact not in stem and pretty.lower() not in stem:
                continue

        weight = "regular"
        for token, mapped in (
            ("thin", "light"),
            ("extralight", "light"),
            ("ultralight", "light"),
            ("light", "light"),
            ("medium", "medium"),
            ("semibold", "semibold"),
            ("demibold", "semibold"),
            ("bold", "bold"),
            ("extrabold", "black"),
            ("black", "black"),
            ("heavy", "black"),
            ("regular", "regular"),
        ):
            if token in stem:
                weight = mapped
                break
        results.append((path.resolve(), weight))
    return results


def _extract_layer_font_family(layer: object) -> str | None:
    if isinstance(layer, dict):
        layer_type = layer.get("layer_type")
        if layer_type not in (None, "text"):
            # Only text layers carry typography; skip others unless family present.
            if "font_family" not in layer:
                return None
        family = layer.get("font_family")
        if isinstance(family, str) and family.strip():
            return family.strip()
        return None

    layer_type = getattr(layer, "layer_type", None)
    if layer_type is not None and layer_type != "text":
        return None
    family = getattr(layer, "font_family", None)
    if isinstance(family, str) and family.strip():
        return family.strip()
    return None


_GLOBAL_MANAGER: FontManagerService | None = None
_GLOBAL_MANAGER_LOCK = threading.Lock()


def get_font_manager_service() -> FontManagerService:
    """Return the process-singleton ``FontManagerService``."""

    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER
    with _GLOBAL_MANAGER_LOCK:
        if _GLOBAL_MANAGER is None:
            _GLOBAL_MANAGER = FontManagerService()
        return _GLOBAL_MANAGER


def reset_font_manager_service_for_tests() -> None:
    """Drop the singleton (unit tests only)."""

    global _GLOBAL_MANAGER
    with _GLOBAL_MANAGER_LOCK:
        _GLOBAL_MANAGER = None
