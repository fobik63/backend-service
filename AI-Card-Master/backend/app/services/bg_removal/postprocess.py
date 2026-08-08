"""Alpha edge cleanup and colour defringing for rembg cutouts."""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image

try:
    import cv2
except ImportError:  # pragma: no cover - optional until opencv is installed
    cv2 = None  # type: ignore[assignment]

# Shrink fringe junk (white dust / halo stubs) before soft edge blur.
DEFAULT_ERODE_PX: Final[int] = 2
# Light Gaussian soften after erosion (px sigma).
DEFAULT_EDGE_BLUR_SIGMA: Final[float] = 0.85
# Pixels at/above this alpha are treated as solid product interior.
DEFAULT_SOLID_ALPHA: Final[int] = 250
# How many solid pixels inward from the silhouette count as "true interior".
DEFAULT_INTERIOR_INSET_PX: Final[int] = 2
# Max radius (px) to propagate interior colours into the fringe.
DEFAULT_DEFRINGE_RADIUS: Final[int] = 16


def refine_cutout_rgba(
    image: Image.Image,
    *,
    erode_px: int = DEFAULT_ERODE_PX,
    edge_blur_sigma: float = DEFAULT_EDGE_BLUR_SIGMA,
    solid_alpha: int = DEFAULT_SOLID_ALPHA,
    interior_inset_px: int = DEFAULT_INTERIOR_INSET_PX,
    defringe_radius: int = DEFAULT_DEFRINGE_RADIUS,
) -> Image.Image:
    """Erode + soften alpha, then defringe semi-transparent edge colours."""

    rgba = image.convert("RGBA")
    arr = np.asarray(rgba, dtype=np.uint8).copy()
    arr = refine_alpha_edges(
        arr,
        erode_px=erode_px,
        edge_blur_sigma=edge_blur_sigma,
    )
    arr = defringe_edge_colors(
        arr,
        solid_alpha=solid_alpha,
        interior_inset_px=interior_inset_px,
        max_radius=defringe_radius,
    )
    return Image.fromarray(arr, mode="RGBA")


def refine_alpha_edges(
    rgba: NDArray[np.uint8],
    *,
    erode_px: int = DEFAULT_ERODE_PX,
    edge_blur_sigma: float = DEFAULT_EDGE_BLUR_SIGMA,
) -> NDArray[np.uint8]:
    """Morphologically erode alpha (1–2 px) and lightly blur the perimeter."""

    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("rgba must be an HxWx4 uint8 array.")

    out = rgba.copy()
    alpha = out[:, :, 3]
    eroded = _erode_alpha(alpha, erode_px=max(0, int(erode_px)))
    if edge_blur_sigma > 0:
        eroded = _gaussian_blur_u8(eroded, sigma=float(edge_blur_sigma))
    # Drop near-zero dust left after blur (white speckles / hairline debris).
    eroded = np.where(eroded < 10, 0, eroded).astype(np.uint8)
    out[:, :, 3] = eroded
    # Fully transparent → zero RGB (avoids leftover fringe colour in encoders).
    transparent = out[:, :, 3] == 0
    out[transparent, :3] = 0
    return out


def defringe_edge_colors(
    rgba: NDArray[np.uint8],
    *,
    solid_alpha: int = DEFAULT_SOLID_ALPHA,
    interior_inset_px: int = DEFAULT_INTERIOR_INSET_PX,
    max_radius: int = DEFAULT_DEFRINGE_RADIUS,
) -> NDArray[np.uint8]:
    """Replace fringe RGB with colours from the nearest solid interior pixels.

    Semi-transparent border pixels — and the outer rim of near-opaque pixels —
    often still carry the original studio / white background. We treat only
    pixels inset from the silhouette as trustworthy colour seeds, then push
    those colours outward into the fringe while preserving the refined alpha.
    """

    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("rgba must be an HxWx4 uint8 array.")

    out = rgba.copy()
    alpha = out[:, :, 3]
    threshold = int(np.clip(solid_alpha, 1, 255))
    solid = alpha >= threshold
    visible = alpha > 0
    if not np.any(visible) or not np.any(solid):
        return out

    interior = _erode_bool_mask(solid, px=max(0, int(interior_inset_px)))
    if not np.any(interior):
        interior = solid

    # Clean both translucent fringe and the contaminated opaque rim.
    fringe = visible & ~interior
    if not np.any(fringe):
        return out

    grown_rgb = _propagate_solid_colors(
        out[:, :, :3],
        solid=interior,
        max_radius=max(1, int(max_radius)),
    )
    out[fringe, :3] = grown_rgb[fringe]
    return out


def _erode_bool_mask(mask: NDArray[np.bool_], *, px: int) -> NDArray[np.bool_]:
    if px <= 0:
        return mask.copy()
    eroded = _erode_alpha((mask.astype(np.uint8) * 255), erode_px=px)
    return eroded > 0


def _erode_alpha(alpha: NDArray[np.uint8], *, erode_px: int) -> NDArray[np.uint8]:
    if erode_px <= 0:
        return alpha.copy()

    if cv2 is not None:
        k = 2 * erode_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        return cv2.erode(alpha, kernel, iterations=1)

    # Pillow fallback: MinFilter shrinks bright (opaque) regions.
    size = 2 * erode_px + 1
    img = Image.fromarray(alpha, mode="L")
    from PIL import ImageFilter

    return np.asarray(img.filter(ImageFilter.MinFilter(size=size)), dtype=np.uint8)


def _gaussian_blur_u8(channel: NDArray[np.uint8], *, sigma: float) -> NDArray[np.uint8]:
    if sigma <= 0:
        return channel.copy()

    if cv2 is not None:
        # ksize=0 → OpenCV derives kernel from sigma.
        blurred = cv2.GaussianBlur(
            channel,
            ksize=(0, 0),
            sigmaX=float(sigma),
            sigmaY=float(sigma),
            borderType=cv2.BORDER_REPLICATE,
        )
        return np.asarray(blurred, dtype=np.uint8)

    from PIL import ImageFilter

    img = Image.fromarray(channel, mode="L")
    return np.asarray(
        img.filter(ImageFilter.GaussianBlur(radius=float(sigma))),
        dtype=np.uint8,
    )


def _propagate_solid_colors(
    rgb: NDArray[np.uint8],
    *,
    solid: NDArray[np.bool_],
    max_radius: int,
) -> NDArray[np.uint8]:
    """Dilate solid RGB colours into neighbouring fringe / empty pixels."""

    if cv2 is not None:
        return _propagate_solid_colors_cv2(rgb, solid=solid, max_radius=max_radius)
    return _propagate_solid_colors_numpy(rgb, solid=solid, max_radius=max_radius)


def _propagate_solid_colors_cv2(
    rgb: NDArray[np.uint8],
    *,
    solid: NDArray[np.bool_],
    max_radius: int,
) -> NDArray[np.uint8]:
    assert cv2 is not None
    grown_mask = (solid.astype(np.uint8)) * 255
    grown_rgb = rgb.astype(np.float32)
    grown_rgb[grown_mask == 0] = 0.0
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for _ in range(max_radius):
        dilated_mask = cv2.dilate(grown_mask, kernel)
        new_pixels = (dilated_mask > 0) & (grown_mask == 0)
        if not np.any(new_pixels):
            break
        for channel in range(3):
            dilated_ch = cv2.dilate(grown_rgb[:, :, channel], kernel)
            grown_rgb[:, :, channel][new_pixels] = dilated_ch[new_pixels]
        grown_mask = dilated_mask

    return np.clip(grown_rgb, 0, 255).astype(np.uint8)


def _propagate_solid_colors_numpy(
    rgb: NDArray[np.uint8],
    *,
    solid: NDArray[np.bool_],
    max_radius: int,
) -> NDArray[np.uint8]:
    """Nearest-solid colour fill without OpenCV (slightly slower)."""

    # Flattened coordinates of solid seeds.
    ys, xs = np.nonzero(solid)
    if ys.size == 0:
        return rgb.copy()

    seed_y = ys.astype(np.int32)
    seed_x = xs.astype(np.int32)
    seed_rgb = rgb[ys, xs].astype(np.uint8)

    out = rgb.copy()
    fringe_ys, fringe_xs = np.nonzero(~solid)
    if fringe_ys.size == 0:
        return out

    # Chunked brute-force nearest seed (fine for product cutouts / local fallback).
    chunk = 4096
    best_idx = np.empty(fringe_ys.size, dtype=np.int32)
    best_dist = np.full(fringe_ys.size, np.inf, dtype=np.float64)
    for start in range(0, fringe_ys.size, chunk):
        stop = min(start + chunk, fringe_ys.size)
        fy = fringe_ys[start:stop].astype(np.float64)[:, None]
        fx = fringe_xs[start:stop].astype(np.float64)[:, None]
        # Subsample seeds if huge; otherwise full set.
        if seed_y.size > 50_000:
            step = max(1, seed_y.size // 25_000)
            sy = seed_y[::step].astype(np.float64)[None, :]
            sx = seed_x[::step].astype(np.float64)[None, :]
            base = np.arange(0, seed_y.size, step, dtype=np.int32)
        else:
            sy = seed_y.astype(np.float64)[None, :]
            sx = seed_x.astype(np.float64)[None, :]
            base = np.arange(seed_y.size, dtype=np.int32)

        dist2 = (fy - sy) ** 2 + (fx - sx) ** 2
        local = np.argmin(dist2, axis=1)
        local_dist = dist2[np.arange(stop - start), local]
        update = local_dist < best_dist[start:stop]
        best_dist[start:stop][update] = local_dist[update]
        best_idx[start:stop][update] = base[local[update]]

    # Cap propagation radius: leave pixels beyond max_radius untouched.
    within = best_dist <= float(max_radius * max_radius)
    fy_ok = fringe_ys[within]
    fx_ok = fringe_xs[within]
    out[fy_ok, fx_ok] = seed_rgb[best_idx[within]]
    return out
