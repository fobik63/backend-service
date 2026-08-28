"""Image upload access control and signature checks."""

from __future__ import annotations

import pytest

from app.api.dependencies.auth import get_current_user
from app.api.images import UploadImageResponse, router
from app.application.generation_errors import GenerationUnsupportedMediaError
from app.application.generation_image_validation import validate_image


def test_upload_image_requires_current_user() -> None:
    route = next(
        r
        for r in router.routes
        if getattr(r, "path", "").endswith("/upload")
        and "POST" in getattr(r, "methods", set())
    )
    calls = [dep.call for dep in route.dependant.dependencies]
    assert get_current_user in calls


def test_upload_response_omits_filesystem_location() -> None:
    assert "location" not in UploadImageResponse.model_fields
    assert "public_path" in UploadImageResponse.model_fields


@pytest.mark.asyncio
async def test_validate_image_rejects_html_polyglot() -> None:
    with pytest.raises(GenerationUnsupportedMediaError):
        await validate_image(b"<html>not-an-image</html>", "image/jpeg")
