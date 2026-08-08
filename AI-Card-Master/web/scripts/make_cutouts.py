"""Remove near-white studio backgrounds from product photos → transparent PNGs."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "public" / "landing"

JOBS = [
    ("perfume-raw.png", "perfume-transparent.png"),
    ("headphones-raw.png", "headphones-transparent.png"),
    ("cosmetics-raw.png", "cosmetics-transparent.png"),
    ("stationery-raw.png", "stationery-transparent.png"),
]


def punch_white(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    pixels = img.load()
    assert pixels is not None
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r > 245 and g > 245 and b > 245:
                pixels[x, y] = (r, g, b, 0)
            elif r > 228 and g > 228 and b > 228:
                whiteness = min(r, g, b)
                alpha = int(max(0, (245 - whiteness) * (255 / 17)))
                pixels[x, y] = (r, g, b, alpha)
    bbox = img.getbbox()
    if bbox:
        pad = 24
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(w, bbox[2] + pad)
        bottom = min(h, bbox[3] + pad)
        img = img.crop((left, top, right, bottom))
    return img


def main() -> None:
    for src_name, dst_name in JOBS:
        src = ROOT / src_name
        dst = ROOT / dst_name
        if not src.exists():
            print(f"SKIP missing {src}")
            continue
        out = punch_white(Image.open(src))
        out.save(dst, "PNG")
        print(f"OK {dst_name} {out.size} -> {dst.stat().st_size} bytes")


if __name__ == "__main__":
    main()
