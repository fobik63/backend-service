"""Regression tests for the versioned multi-page editor contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.templates import EditorDocumentDTO


def _document_payload() -> dict[str, object]:
    return {
        "version": 1,
        "pages": [
            {
                "id": "page-1",
                "layers": [
                    {
                        "id": "layer-bg",
                        "type": "background",
                        "name": "Фон",
                        "visible": True,
                        "locked": True,
                        "opacity": 1.0,
                        "z_index": 0,
                        "x": 0.0,
                        "y": 0.0,
                        "width": 100.0,
                        "height": 100.0,
                        "scale": 1.0,
                        "rotation": 0.0,
                    }
                ],
            }
        ],
        "active_page_index": 0,
        "pack_size": 1,
        "product_preview_url": "https://cdn.example/product.png",
        "softbox": {
            "enabled": True,
            "light_angle": 45.0,
            "light_elevation": 55.0,
            "color_temp_k": 5500,
            "intensity": 100.0,
            "softbox_diffusion": 65.0,
        },
    }


def test_editor_document_round_trip_preserves_pages() -> None:
    document = EditorDocumentDTO.model_validate(_document_payload())

    restored = EditorDocumentDTO.model_validate(document.model_dump(mode="json"))

    assert restored == document
    assert restored.pages[0].layers[0].id == "layer-bg"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pack_size", 2),
        ("active_page_index", 1),
    ],
)
def test_editor_document_rejects_inconsistent_page_bounds(
    field: str,
    value: int,
) -> None:
    payload = _document_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        EditorDocumentDTO.model_validate(payload)
