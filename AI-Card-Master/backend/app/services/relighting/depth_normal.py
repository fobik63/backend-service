"""Depth & normal map estimation from a 2D product image (Pillow + NumPy).

Lightweight local estimate suitable for studio relighting without ControlNet /
GPU inference. Depth combines silhouette distance-from-edge with luminance;
normals are derived from depth gradients (Sobel-like).
"""

from __future__ import annotations

import io
from statistics import median

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError

from app.services.relighting.dto import DepthNormalMapsDTO


class DepthNormalEstimationError(ValueError):
    """Raised when depth / normal maps cannot be estimated."""


def estimate_depth_and_normals(image_bytes: bytes) -> DepthNormalMapsDTO:
    """Build depth (L), normal (RGB), and alpha mask (L) PNGs from a product shot."""

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DepthNormalEstimationError(
            "Product image cannot be decoded for depth/normal estimation."
        ) from exc

    mask = _extract_product_mask(rgba)
    bbox = mask.getbbox()
    if bbox is None:
        raise DepthNormalEstimationError("Could not extract a non-empty product mask.")

    depth = _estimate_depth(rgba, mask)
    normals = _normals_from_depth(depth, mask)

    depth_buf = io.BytesIO()
    depth.save(depth_buf, format="PNG", optimize=True, compress_level=6)
    normal_buf = io.BytesIO()
    normals.save(normal_buf, format="PNG", optimize=True, compress_level=6)
    mask_buf = io.BytesIO()
    mask.save(mask_buf, format="PNG", optimize=True, compress_level=6)

    return DepthNormalMapsDTO(
        depth_png=depth_buf.getvalue(),
        normal_png=normal_buf.getvalue(),
        mask_png=mask_buf.getvalue(),
        width=rgba.width,
        height=rgba.height,
    )


def load_rgba(image_bytes: bytes) -> Image.Image:
    """Decode image bytes to RGBA (shared by engine / shadows)."""

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            return ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DepthNormalEstimationError(
            "Product image cannot be decoded."
        ) from exc


def extract_product_mask(rgba: Image.Image) -> Image.Image:
    """Public wrapper for product alpha / chroma-key mask extraction."""

    return _extract_product_mask(rgba)


def _extract_product_mask(product: Image.Image) -> Image.Image:
    alpha = product.getchannel("A")
    first_non_empty_alpha = next(
        (value for value, count in enumerate(alpha.histogram()) if count),
        255,
    )
    if first_non_empty_alpha < 250:
        return alpha.point(lambda pixel: 255 if pixel >= 12 else 0).filter(
            ImageFilter.MaxFilter(5)
        )

    rgb = product.convert("RGB")
    samples = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((rgb.width - 1, 0)),
        rgb.getpixel((0, rgb.height - 1)),
        rgb.getpixel((rgb.width - 1, rgb.height - 1)),
    ]
    background = tuple(int(median(channel)) for channel in zip(*samples, strict=True))
    background_image = Image.new("RGB", rgb.size, background)
    difference = ImageChops.difference(rgb, background_image).convert("L")
    histogram = difference.histogram()
    total = max(1, rgb.width * rgb.height)
    cumulative = 0
    percentile = 18
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative / total >= 0.70:
            percentile = value
            break
    threshold = max(16, min(64, percentile + 10))
    mask = difference.point(lambda pixel: 255 if pixel >= threshold else 0)
    mask = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MedianFilter(5))
    bbox = mask.getbbox()
    coverage = sum(value * count for value, count in enumerate(mask.histogram())) / (
        255 * total
    )
    if bbox is None or coverage < 0.01 or coverage > 0.95:
        mask = Image.new("L", rgb.size, 0)
        inset_x = max(1, rgb.width // 12)
        inset_y = max(1, rgb.height // 12)
        central = Image.new(
            "L",
            (rgb.width - 2 * inset_x, rgb.height - 2 * inset_y),
            255,
        )
        mask.paste(central, (inset_x, inset_y))
    return mask


def _estimate_depth(rgba: Image.Image, mask: Image.Image) -> Image.Image:
    """Soft depth: inward distance from silhouette + luminance cue."""

    binary = np.asarray(mask, dtype=np.uint8) > 0
    if not np.any(binary):
        return Image.new("L", rgba.size, 0)

    # Approximate Euclidean distance-from-edge via iterative erosion counts.
    distance = np.zeros(binary.shape, dtype=np.float32)
    remaining = binary.copy()
    step = 1.0
    # Cap iterations to keep CPU bounded on large images.
    max_steps = max(8, min(rgba.width, rgba.height) // 4)
    for _ in range(max_steps):
        if not np.any(remaining):
            break
        eroded = _erode_bool(remaining)
        frontier = remaining & ~eroded
        distance[frontier] = step
        remaining = eroded
        step += 1.0

    if distance.max() > 0:
        distance /= distance.max()

    luminance = np.asarray(rgba.convert("L"), dtype=np.float32) / 255.0
    depth = (0.65 * distance + 0.35 * luminance * binary.astype(np.float32)) * 255.0
    depth = np.clip(depth, 0, 255).astype(np.uint8)
    depth[~binary] = 0
    depth_img = Image.fromarray(depth, mode="L")
    return depth_img.filter(ImageFilter.GaussianBlur(radius=1.2))


def _erode_bool(mask: np.ndarray) -> np.ndarray:
    """3×3 binary erosion without SciPy."""

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            out &= padded[1 + dy : 1 + dy + mask.shape[0], 1 + dx : 1 + dx + mask.shape[1]]
    return out


def _normals_from_depth(depth: Image.Image, mask: Image.Image) -> Image.Image:
    """Encode camera-facing normals as RGB (OpenGL-style: +X right, +Y up, +Z out)."""

    z = np.asarray(depth, dtype=np.float32) / 255.0
    # Sobel kernels
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    dzdx = _convolve2d(z, kx)
    dzdy = _convolve2d(z, ky)

    # Scale gradients so typical product curvature yields visible shading.
    strength = 2.4
    nx = -dzdx * strength
    ny = -dzdy * strength
    nz = np.ones_like(z)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    norm = np.maximum(norm, 1e-6)
    nx /= norm
    ny /= norm
    nz /= norm

    rgb = np.stack(
        (
            ((nx + 1.0) * 0.5 * 255.0),
            ((ny + 1.0) * 0.5 * 255.0),
            ((nz + 1.0) * 0.5 * 255.0),
        ),
        axis=-1,
    ).astype(np.uint8)

    binary = np.asarray(mask, dtype=np.uint8) > 0
    rgb[~binary] = (128, 128, 255)  # flat facing camera outside product
    return Image.fromarray(rgb, mode="RGB")


def _convolve2d(data: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Valid-ish same-size convolution with reflect padding."""

    kh, kw = kernel.shape
    pad_y, pad_x = kh // 2, kw // 2
    padded = np.pad(data, ((pad_y, pad_y), (pad_x, pad_x)), mode="reflect")
    out = np.zeros_like(data, dtype=np.float32)
    for y in range(kh):
        for x in range(kw):
            coeff = float(kernel[y, x])
            if coeff == 0.0:
                continue
            out += coeff * padded[y : y + data.shape[0], x : x + data.shape[1]]
    return out
