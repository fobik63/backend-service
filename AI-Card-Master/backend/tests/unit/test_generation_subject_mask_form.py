"""GenerationForm accepts subject-preservation and editor cover-only flags."""

from __future__ import annotations

import pytest

from app.schemas.generations import GenerationForm


def test_generation_form_defaults_preserve_subject() -> None:
    form = GenerationForm()
    assert form.preserve_subject is True
    assert form.editor_cover_only is False
    assert form.style_prompt is None
    assert form.apply_text_overlays is False


def test_generation_form_editor_cover_only_and_style_prompt() -> None:
    form = GenerationForm(
        preserve_subject=True,
        editor_cover_only=True,
        style_prompt="  Soft marble studio with cool rim light  ",
        apply_text_overlays=False,
    )
    assert form.editor_cover_only is True
    assert form.style_prompt == "Soft marble studio with cool rim light"


def test_generation_form_rejects_blank_style_prompt_as_none() -> None:
    form = GenerationForm(style_prompt="   ")
    assert form.style_prompt is None


def test_build_editor_background_task_uses_prompt() -> None:
    from app.services.series_generator import (
        EDITOR_BG_SLIDE_KEY,
        build_editor_background_task,
    )

    task = build_editor_background_task(style_prompt="Neon cyber shelf")
    assert task.slide_key == EDITOR_BG_SLIDE_KEY
    assert task.user_text == "Neon cyber shelf"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_generation_form_bool_fields(value: bool, expected: bool) -> None:
    form = GenerationForm(preserve_subject=value, editor_cover_only=value)
    assert form.preserve_subject is expected
    assert form.editor_cover_only is expected
