/**
 * Marketplace card format presets + smart artboard scaling.
 * Layer geometry is %-based; absolute text/chip metrics are scaled when the
 * artboard pixel size (or aspect) changes so the layout does not "slide".
 */

import type { CanvasLayer } from "@/types/canvas"

export type ArtboardFormatId =
  | "wb-1080"
  | "wb-900"
  | "wb-1500"
  | "ozon-1-1"
  | "yandex-3-4"
  | "yandex-1-1"

export type ArtboardFormatPreset = {
  id: ArtboardFormatId
  /** Marketplace group for the format selector. */
  marketplace: "wildberries" | "ozon" | "yandex"
  width: number
  height: number
  ratio: "3:4" | "1:1"
  /** Default safe-zone mask when this format is selected. */
  safeZone: "wb" | "ozon" | "off"
  /** i18n key under editor.* */
  labelKey:
    | "formatWb1080"
    | "formatWb900"
    | "formatWb1500"
    | "formatOzon"
    | "formatYandex34"
    | "formatYandex11"
}

export const ARTBOARD_FORMAT_PRESETS: ArtboardFormatPreset[] = [
  {
    id: "wb-1080",
    marketplace: "wildberries",
    width: 1080,
    height: 1440,
    ratio: "3:4",
    safeZone: "wb",
    labelKey: "formatWb1080",
  },
  {
    id: "wb-900",
    marketplace: "wildberries",
    width: 900,
    height: 1200,
    ratio: "3:4",
    safeZone: "wb",
    labelKey: "formatWb900",
  },
  {
    id: "wb-1500",
    marketplace: "wildberries",
    width: 1500,
    height: 2000,
    ratio: "3:4",
    safeZone: "wb",
    labelKey: "formatWb1500",
  },
  {
    id: "ozon-1-1",
    marketplace: "ozon",
    width: 1200,
    height: 1200,
    ratio: "1:1",
    safeZone: "ozon",
    labelKey: "formatOzon",
  },
  {
    id: "yandex-3-4",
    marketplace: "yandex",
    width: 900,
    height: 1200,
    ratio: "3:4",
    safeZone: "off",
    labelKey: "formatYandex34",
  },
  {
    id: "yandex-1-1",
    marketplace: "yandex",
    width: 1200,
    height: 1200,
    ratio: "1:1",
    safeZone: "off",
    labelKey: "formatYandex11",
  },
]

/** Default editor artboard — WB 3:4 at 1080×1440. */
export const DEFAULT_ARTBOARD_FORMAT_ID: ArtboardFormatId = "wb-1080"

export const DEFAULT_ARTBOARD_WIDTH = 1080
export const DEFAULT_ARTBOARD_HEIGHT = 1440

export function getArtboardPreset(
  id: ArtboardFormatId
): ArtboardFormatPreset {
  return (
    ARTBOARD_FORMAT_PRESETS.find((preset) => preset.id === id) ??
    ARTBOARD_FORMAT_PRESETS[0]!
  )
}

export function resolveArtboardSize(id: ArtboardFormatId): {
  width: number
  height: number
} {
  const preset = getArtboardPreset(id)
  return { width: preset.width, height: preset.height }
}

export type ArtboardSize = { width: number; height: number }

/**
 * Smart-scale layers when switching artboard size.
 * - %-geometry stays relative to the new artboard (full-bleed bg stays 100%).
 * - Absolute font / stroke / chip metrics scale by the geometric mean of
 *   width/height ratios so vectors and type stay crisp and proportional.
 * - When aspect ratio changes, Y positions are remapped around the artboard
 *   center so content does not drift toward the top/bottom edge.
 */
export function smartScalePages(
  pages: CanvasLayer[][],
  from: ArtboardSize,
  to: ArtboardSize
): CanvasLayer[][] {
  if (from.width === to.width && from.height === to.height) {
    return pages
  }

  const sx = to.width / Math.max(1, from.width)
  const sy = to.height / Math.max(1, from.height)
  const metricScale = Math.sqrt(sx * sy)
  const fromAspect = from.width / Math.max(1, from.height)
  const toAspect = to.width / Math.max(1, to.height)
  const aspectChanged = Math.abs(fromAspect - toAspect) > 0.02

  return pages.map((page) =>
    page.map((layer) => scaleLayer(layer, metricScale, aspectChanged, fromAspect, toAspect))
  )
}

function scaleLayer(
  layer: CanvasLayer,
  metricScale: number,
  aspectChanged: boolean,
  fromAspect: number,
  toAspect: number
): CanvasLayer {
  if (layer.type === "background") {
    return {
      ...layer,
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      scale: 1,
    }
  }

  let x = layer.x ?? 0
  let y = layer.y ?? 0
  let width = layer.width
  let height = layer.height

  // Remap vertical placement when aspect flips (3:4 ↔ 1:1) around center.
  if (aspectChanged && y != null) {
    const h = height ?? (layer.type === "shape" ? 9 : 12)
    const centerY = y + h / 2
    // Compress/expand distance from mid-line by aspect ratio change.
    const mid = 50
    const rel = centerY - mid
    const aspectFactor = Math.sqrt(fromAspect / toAspect)
    const nextCenter = mid + rel * aspectFactor
    y = nextCenter - h / 2
  }

  const next: CanvasLayer = {
    ...layer,
    x,
    y,
    width,
    height,
    textStyle: layer.textStyle
      ? {
          ...layer.textStyle,
          fontSize: clamp(
            Math.round(layer.textStyle.fontSize * metricScale),
            8,
            512
          ),
          strokeWidth: round2(layer.textStyle.strokeWidth * metricScale),
          shadowBlur: round2(layer.textStyle.shadowBlur * metricScale),
          shadowOffsetX: round2(layer.textStyle.shadowOffsetX * metricScale),
          shadowOffsetY: round2(layer.textStyle.shadowOffsetY * metricScale),
        }
      : layer.textStyle,
    chip: layer.chip
      ? {
          ...layer.chip,
          borderRadius: round2(layer.chip.borderRadius * metricScale),
          blur: round2((layer.chip.blur ?? 0) * metricScale),
          strokeWidth:
            layer.chip.strokeWidth != null
              ? round2(layer.chip.strokeWidth * metricScale)
              : layer.chip.strokeWidth,
        }
      : layer.chip,
  }
  return next
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}
