"""Unit tests for FontManagerService (signature, fallback, metadata)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from app.services.templates.font_manager import (
    DEFAULT_FALLBACK_FAMILY,
    FontManagerService,
    FontValidationError,
    parse_font_metadata,
    reset_font_manager_service_for_tests,
)
from app.services.templates.fonts import FontRegistry


def _minimal_ttf_bytes(*, family: str = "TestFamily", style: str = "Regular") -> bytes:
    """Build a tiny valid TrueType font via fontTools for upload tests."""

    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.lineTo((100, 100))
    pen.lineTo((0, 100))
    pen.closePath()
    glyph = pen.glyph()

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({ord("A"): "A"})
    fb.setupGlyf({".notdef": glyph, "A": glyph})
    fb.setupHorizontalMetrics({".notdef": (100, 0), "A": (100, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "uniqueFontIdentifier": f"{family}-{style}",
            "fullName": f"{family} {style}",
            "psName": f"{family.replace(' ', '')}-{style}",
            "version": "1.0",
        }
    )
    fb.setupOS2()
    fb.setupPost()
    buffer = BytesIO()
    fb.save(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _reset_manager() -> None:
    reset_font_manager_service_for_tests()
    yield
    reset_font_manager_service_for_tests()


def test_assert_rejects_non_font_payload(tmp_path: Path) -> None:
    manager = FontManagerService(
        registry=FontRegistry(extra_search_dirs=[]),
        assets_dir=tmp_path / "assets",
        custom_dir=tmp_path / "custom",
    )
    assert manager is not None
    with pytest.raises(FontValidationError, match="signature"):
        # Exercise validation path without DB via parse helpers.
        from app.services.templates.font_manager import _assert_font_signature

        _assert_font_signature(b"not-a-font-file!!!!")


def test_parse_font_metadata_from_minimal_ttf() -> None:
    payload = _minimal_ttf_bytes(family="CoolSans", style="Bold")
    meta = parse_font_metadata(payload, extension=".ttf")
    assert meta.font_family == "CoolSans"
    assert meta.font_weight == "bold"
    assert "CoolSans" in meta.font_name


def test_resolve_family_falls_back_to_inter(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    registry = FontRegistry(extra_search_dirs=[])
    manager = FontManagerService(
        registry=registry,
        assets_dir=tmp_path / "assets",
        custom_dir=tmp_path / "custom",
        fallback_family=DEFAULT_FALLBACK_FAMILY,
    )
    # Seed Inter as the only known family.
    inter_file = tmp_path / "assets" / "Inter-Regular.ttf"
    inter_file.parent.mkdir(parents=True)
    inter_file.write_bytes(_minimal_ttf_bytes(family="Inter", style="Regular"))
    registry.register_file(
        font_family="Inter",
        file_path_ttf=inter_file,
        font_weight="regular",
    )
    manager._known_families.add("inter")  # noqa: SLF001 — test seed

    with caplog.at_level("WARNING"):
        result = manager.resolve_family("TotallyMissingDisplayFont")

    assert result.fell_back is True
    assert result.resolved_family == "Inter"
    assert result.requested_family == "TotallyMissingDisplayFont"
    assert "falling back" in caplog.text.lower() or "not registered" in caplog.text.lower()


def test_resolve_canvas_json_layers(tmp_path: Path) -> None:
    registry = FontRegistry(extra_search_dirs=[])
    manager = FontManagerService(
        registry=registry,
        assets_dir=tmp_path / "assets",
        custom_dir=tmp_path / "custom",
    )
    inter_file = tmp_path / "assets" / "Inter-Regular.ttf"
    inter_file.parent.mkdir(parents=True)
    inter_file.write_bytes(_minimal_ttf_bytes(family="Inter"))
    registry.register_file(font_family="Inter", file_path_ttf=inter_file)
    manager._known_families.add("inter")  # noqa: SLF001

    canvas = {
        "layers": [
            {"layer_type": "image", "url": "https://example.com/x.png"},
            {
                "layer_type": "text",
                "font_family": "MissingBrandFont",
                "text": "Hello",
            },
            {
                "layer_type": "text",
                "font_family": "Inter",
                "text": "OK",
            },
        ]
    }
    results = manager.resolve_canvas_font_families(canvas)
    assert len(results) == 2
    assert results[0].fell_back is True
    assert results[0].resolved_family == "Inter"
    assert results[1].fell_back is False


def test_bootstrap_registers_files_from_assets(tmp_path: Path) -> None:
    assets = tmp_path / "fonts"
    assets.mkdir()
    (assets / "Montserrat-Regular.ttf").write_bytes(
        _minimal_ttf_bytes(family="Montserrat")
    )
    registry = FontRegistry(extra_search_dirs=[])
    manager = FontManagerService(
        registry=registry,
        assets_dir=assets,
        custom_dir=tmp_path / "custom",
    )

    import asyncio

    count = asyncio.run(manager.bootstrap(persist_system_fonts=False))
    assert count >= 1
    assert manager.has_family("Montserrat")
