"""Compose transparent cutouts onto a gray studio backdrop for «До» slides."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

LAND = Path(__file__).resolve().parents[1] / "public" / "landing"

JOBS: list[tuple[str, str, tuple[float, float]]] = [
    ("perfume-transparent.png", "before-perfume.png", (0.62, 0.72)),
    ("stationery-transparent.png", "before-stationery.png", (0.55, 0.78)),
    ("cosmetics-transparent.png", "before-cosmetics.png", (0.58, 0.58)),
]

W, H = 900, 1125
BG = (189, 189, 194, 255)


def main() -> None:
    for src_name, dst_name, (max_w_frac, max_h_frac) in JOBS:
        cut = Image.open(LAND / src_name).convert("RGBA")
        canvas = Image.new("RGBA", (W, H), BG)
        max_w = int(W * max_w_frac)
        max_h = int(H * max_h_frac)
        cw, ch = cut.size
        scale = min(max_w / cw, max_h / ch)
        nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
        cut_r = cut.resize((nw, nh), Image.Resampling.LANCZOS)
        x = (W - nw) // 2
        y = int(H * 0.48 - nh / 2)
        canvas.alpha_composite(cut_r, (x, y))
        canvas.save(LAND / dst_name, "PNG")
        print(f"OK {dst_name} {canvas.size} -> {(LAND / dst_name).stat().st_size} bytes")


if __name__ == "__main__":
    main()
