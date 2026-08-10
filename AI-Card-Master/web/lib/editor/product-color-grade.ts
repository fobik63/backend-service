import {
  filters,
  type FabricImage,
  type TMatColorMatrix,
} from "fabric"

import type { ProductColorGrade } from "@/lib/store/editor-store"

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function nearZero(n: number, eps = 0.001) {
  return Math.abs(n) < eps
}

/** Warm (+) / cold (−) temperature as a 5×4 ColorMatrix. */
export function temperatureColorMatrix(temp: number): TMatColorMatrix {
  const t = clamp(temp, -1, 1)
  const warm = Math.max(0, t)
  const cool = Math.max(0, -t)
  return [
    1 + warm * 0.14,
    0,
    0,
    0,
    warm * 0.03 - cool * 0.02,
    0,
    1 + warm * 0.04 - cool * 0.02,
    0,
    0,
    0,
    0,
    0,
    1 + cool * 0.16,
    0,
    cool * 0.03 - warm * 0.04,
    0,
    0,
    0,
    1,
    0,
  ]
}

/**
 * Approximate shadows / highlights lift via gain + bias.
 * Positive shadows opens darks; positive highlights lifts brights.
 */
export function toneColorMatrix(
  shadows: number,
  highlights: number
): TMatColorMatrix {
  const s = clamp(shadows, -1, 1)
  const h = clamp(highlights, -1, 1)
  const gain = 1 + h * 0.18 - Math.max(0, -s) * 0.08
  const bias = s * 0.14 - h * 0.04
  return [
    gain,
    0,
    0,
    0,
    bias,
    0,
    gain,
    0,
    0,
    bias,
    0,
    0,
    gain,
    0,
    bias,
    0,
    0,
    0,
    1,
    0,
  ]
}

/** Gamma for shadows/highlights: <1 opens shadows, >1 compresses highlights. */
export function toneGamma(
  shadows: number,
  highlights: number
): [number, number, number] {
  const s = clamp(shadows, -1, 1)
  const h = clamp(highlights, -1, 1)
  // Fabric Gamma: lower values brighten midtones (opens shadows).
  const g = clamp(1 - s * 0.35 + h * 0.25, 0.2, 2.2)
  return [g, g, g]
}

function sharpenMatrix(sharpness: number): number[] {
  const amount = clamp(sharpness, 0, 1)
  return [0, -amount, 0, -amount, 1 + amount * 4, -amount, 0, -amount, 0]
}

/**
 * Build Fabric filter stack for fast client-side color correction.
 * Neutral knobs are omitted so WebGL skips no-op passes.
 *
 * Rim uses a gentle screen blend only; sharpness is a separate, explicit
 * Convolute pass controlled by the user.
 */
export function buildProductColorFilters(
  grade: ProductColorGrade
): InstanceType<typeof filters.BaseFilter>[] {
  const list: InstanceType<typeof filters.BaseFilter>[] = []

  if (!nearZero(grade.brightness)) {
    list.push(new filters.Brightness({ brightness: clamp(grade.brightness, -1, 1) }))
  }
  if (!nearZero(grade.contrast)) {
    list.push(new filters.Contrast({ contrast: clamp(grade.contrast, -1, 1) }))
  }
  if (!nearZero(grade.saturation)) {
    list.push(new filters.Saturation({ saturation: clamp(grade.saturation, -1, 1) }))
  }
  if (!nearZero(grade.hue)) {
    list.push(new filters.HueRotation({ rotation: clamp(grade.hue, -1, 1) }))
  }
  if (!nearZero(grade.temperature)) {
    list.push(
      new filters.ColorMatrix({
        matrix: temperatureColorMatrix(grade.temperature),
        colorsOnly: true,
      })
    )
  }
  if (!nearZero(grade.shadows) || !nearZero(grade.highlights)) {
    list.push(
      new filters.ColorMatrix({
        matrix: toneColorMatrix(grade.shadows, grade.highlights),
        colorsOnly: true,
      })
    )
    const gamma = toneGamma(grade.shadows, grade.highlights)
    if (!nearZero(gamma[0] - 1, 0.01)) {
      list.push(new filters.Gamma({ gamma }))
    }
  }

  // Soft rim wash — keep silhouette clean (no Convolute / edge sharpen).
  if (grade.rimEnabled && grade.rimStrength > 0) {
    const strength = clamp(grade.rimStrength / 100, 0, 1)
    list.push(
      new filters.BlendColor({
        color: grade.rimColor || "#f5f7fb",
        mode: "screen",
        alpha: 0.03 + strength * 0.14,
      })
    )
  }
  if (grade.sharpness > 0) {
    list.push(new filters.Convolute({ matrix: sharpenMatrix(grade.sharpness) }))
  }

  return list
}

export function isColorGradeNeutral(grade: ProductColorGrade): boolean {
  return (
    nearZero(grade.brightness) &&
    nearZero(grade.contrast) &&
    nearZero(grade.saturation) &&
    nearZero(grade.hue) &&
    nearZero(grade.temperature) &&
    nearZero(grade.highlights) &&
    nearZero(grade.shadows) &&
    nearZero(grade.sharpness) &&
    !(grade.rimEnabled && grade.rimStrength > 0)
  )
}

/** Apply (or clear) GPU-backed color-grade filters on a FabricImage. */
export function applyImageColorGrade(
  img: FabricImage,
  grade: ProductColorGrade
): void {
  const next = isColorGradeNeutral(grade) ? [] : buildProductColorFilters(grade)
  img.filters = next
  img.applyFilters()
  // Keep objectCaching off — a low-res cache + WebGL filter bake made cutouts
  // look grainy / toy-like when the source PNG exceeded the GL texture cap.
  img.set({ dirty: true, objectCaching: false, imageSmoothing: true })
}

/** Apply (or clear) color-grade filters on a product FabricImage. */
export const applyProductColorGrade = applyImageColorGrade
