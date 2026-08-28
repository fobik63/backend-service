"""Unit tests for CanvasPromptParser (NL prompt → CanvasStateDTO JSON)."""

from __future__ import annotations

import json
import re
from uuid import UUID, uuid4

import pytest

from app.schemas.templates import (
    BadgeLayerDTO,
    CanvasStateDTO,
    ImageLayerDTO,
    TextLayerDTO,
)
from app.services.templates.prompt_parser import (
    CanvasPromptParser,
    CanvasPromptParserUpstreamError,
    CanvasPromptParserValidationError,
    build_canvas_parser_user_prompt,
    parse_canvas_json,
)


def _uuid() -> str:
    return str(uuid4())


def _base_canvas() -> CanvasStateDTO:
    return CanvasStateDTO(
        width=1080,
        height=1440,
        background_color="#F5F5F5",
        layers=[
            ImageLayerDTO(
                id=UUID("11111111-1111-1111-1111-111111111111"),
                name="product",
                x=140.0,
                y=280.0,
                width=800.0,
                height=800.0,
                z_index=1,
                url="memory://product.png",
            ),
            TextLayerDTO(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                name="title",
                x=80.0,
                y=80.0,
                width=920.0,
                height=120.0,
                z_index=5,
                text="Product",
                font_family="DejaVuSans",
                font_size=48,
                font_weight="bold",
                color_hex="#111111",
                alignment="left",
            ),
        ],
    )


def _canvas_payload(
    *,
    title: str = "Nike Air",
    title_color: str = "#2563EB",
    font_family: str = "Inter",
    price_text: str = "12900",
    badge_bg: str = "#E11D48",
    product_x: float = 320.0,
) -> dict:
    return {
        "width": 1080,
        "height": 1440,
        "background_color": "#FFFFFF",
        "background_image_url": None,
        "layers": [
            {
                "layer_type": "image",
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "product",
                "x": product_x,
                "y": 280.0,
                "width": 800.0,
                "height": 800.0,
                "z_index": 1,
                "url": "memory://product.png",
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
            {
                "layer_type": "text",
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "title",
                "x": 80.0,
                "y": 80.0,
                "width": 920.0,
                "height": 120.0,
                "z_index": 5,
                "text": title,
                "font_family": font_family,
                "font_size": 56,
                "font_weight": "bold",
                "color_hex": title_color,
                "alignment": "left",
                "line_height": 1.2,
                "letter_spacing": 0.0,
            },
            {
                "layer_type": "badge",
                "id": _uuid(),
                "name": "price-badge",
                "x": 760.0,
                "y": 1240.0,
                "width": 260.0,
                "height": 88.0,
                "z_index": 10,
                "badge_type": "discount",
                "text": price_text,
                "bg_color": badge_bg,
                "text_color": "#FFFFFF",
            },
        ],
    }


class _ScriptedCompleter:
    """Deterministic stand-in that maps prompt keywords to Canvas JSON."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        lower = user.lower()

        title = "Nike Air"
        title_match = re.search(
            r"заголовок\s+['\"]([^'\"]+)['\"]",
            user,
            flags=re.IGNORECASE,
        )
        if title_match:
            title = title_match.group(1)

        title_color = "#111111"
        if re.search(r"заголовок[^\n]{0,80}син", lower) or re.search(
            r"син[^\n]{0,40}шрифт", lower
        ):
            title_color = "#2563EB"
        elif re.search(r"заголовок[^\n]{0,80}красн", lower):
            title_color = "#E11D48"
        elif re.search(r"заголовок[^\n]{0,80}зелён|заголовок[^\n]{0,80}зелен", lower):
            title_color = "#16A34A"

        font_family = "DejaVuSans"
        if "inter" in lower:
            font_family = "Inter"

        price_text = "0"
        price_match = re.search(r"цен[ауые]\s+(\d[\d\s]*)", user, flags=re.IGNORECASE)
        if price_match:
            price_text = re.sub(r"\s+", "", price_match.group(1))
        else:
            en_price = re.search(r"price\s+(\d[\d\s]*)", user, flags=re.IGNORECASE)
            if en_price:
                price_text = re.sub(r"\s+", "", en_price.group(1))

        badge_bg = "#2563EB"
        if re.search(r"красн[^\n]{0,40}(?:бэйдж|бейдж|badge)", lower) or re.search(
            r"(?:бэйдж|бейдж|badge)[^\n]{0,40}красн", lower
        ):
            badge_bg = "#E11D48"

        product_x = 140.0
        if "вправо" in lower or "to the right" in lower:
            product_x = 360.0
        if "влево" in lower or "to the left" in lower:
            product_x = 40.0

        return json.dumps(
            _canvas_payload(
                title=title,
                title_color=title_color,
                font_family=font_family,
                price_text=price_text,
                badge_bg=badge_bg,
                product_x=product_x,
            ),
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_parse_nike_air_blue_inter_red_badge_move_right() -> None:
    completer = _ScriptedCompleter()
    parser = CanvasPromptParser(completer=completer)

    prompt = (
        "Сделай заголовок 'Nike Air' синим шрифтом Inter, "
        "цену 12900 в красный бэйдж и перемести товар вправо"
    )
    canvas = await parser.parse(prompt, base_canvas=_base_canvas())

    assert canvas.width == 1080
    assert canvas.height == 1440
    assert len(completer.calls) == 1

    title = next(layer for layer in canvas.layers if layer.layer_type == "text")
    assert isinstance(title, TextLayerDTO)
    assert title.text == "Nike Air"
    assert title.color_hex == "#2563EB"
    assert title.font_family == "Inter"

    badge = next(layer for layer in canvas.layers if layer.layer_type == "badge")
    assert isinstance(badge, BadgeLayerDTO)
    assert badge.text == "12900"
    assert badge.bg_color == "#E11D48"
    assert badge.badge_type == "discount"

    product = next(layer for layer in canvas.layers if layer.layer_type == "image")
    assert isinstance(product, ImageLayerDTO)
    assert product.x == 360.0
    assert product.name == "product"


@pytest.mark.asyncio
async def test_parse_moves_product_left_and_keeps_green_title() -> None:
    completer = _ScriptedCompleter()
    parser = CanvasPromptParser(completer=completer)

    canvas = await parser.parse(
        "Заголовок 'Trail Pro' зелёным цветом Inter, цену 8990 в бэйдж, товар влево"
    )

    title = next(layer for layer in canvas.layers if layer.layer_type == "text")
    assert title.text == "Trail Pro"
    assert title.font_family == "Inter"

    product = next(layer for layer in canvas.layers if layer.name == "product")
    assert product.x == 40.0

    badge = next(layer for layer in canvas.layers if layer.layer_type == "badge")
    assert badge.text == "8990"


@pytest.mark.asyncio
async def test_parse_english_instruction_to_the_right() -> None:
    completer = _ScriptedCompleter()
    parser = CanvasPromptParser(completer=completer)

    canvas = await parser.parse(
        "Make title 'Air Max' with Inter, price 15000 badge, move product to the right"
    )
    product = next(layer for layer in canvas.layers if layer.name == "product")
    assert product.x == 360.0


def test_parse_canvas_json_accepts_markdown_fenced_payload() -> None:
    payload = _canvas_payload(title="Fenced", price_text="1000")
    raw = f"```json\n{json.dumps(payload)}\n```"
    canvas = parse_canvas_json(raw)
    title = next(layer for layer in canvas.layers if layer.layer_type == "text")
    assert title.text == "Fenced"


def test_parse_canvas_json_rejects_invalid_json() -> None:
    with pytest.raises(CanvasPromptParserUpstreamError, match="not valid JSON"):
        parse_canvas_json("{not-json")


def test_parse_canvas_json_rejects_schema_violations() -> None:
    bad = {
        "width": 1080,
        "height": 1440,
        "background_color": "not-a-hex",
        "layers": [],
    }
    with pytest.raises(CanvasPromptParserValidationError, match="schema"):
        parse_canvas_json(json.dumps(bad))


@pytest.mark.asyncio
async def test_empty_prompt_raises_validation_error() -> None:
    parser = CanvasPromptParser(completer=_ScriptedCompleter())
    with pytest.raises(CanvasPromptParserValidationError, match="non-empty"):
        await parser.parse("   ")


def test_user_prompt_includes_fenced_instruction_and_base_canvas() -> None:
    base = _base_canvas()
    message = build_canvas_parser_user_prompt(
        "Сделай заголовок синим",
        base_canvas=base,
    )
    assert "<untrusted_input" in message
    assert "Сделай заголовок синим" in message
    assert "11111111-1111-1111-1111-111111111111" in message
    assert '"layer_type":"image"' in message or '"layer_type": "image"' in message


@pytest.mark.asyncio
async def test_upstream_invalid_completer_payload_surfaces_error() -> None:
    async def broken(_system: str, _user: str) -> str:
        return "definitely not json"

    parser = CanvasPromptParser(completer=broken)
    with pytest.raises(CanvasPromptParserUpstreamError):
        await parser.parse("Сделай заголовок красным")
