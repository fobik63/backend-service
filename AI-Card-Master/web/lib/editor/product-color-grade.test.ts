import { describe, expect, it } from "vitest"

import {
  buildProductColorFilters,
  isColorGradeNeutral,
  temperatureColorMatrix,
  toneColorMatrix,
} from "@/lib/editor/product-color-grade"
import {
  DEFAULT_COLOR_GRADE,
  type ProductColorGrade,
} from "@/lib/store/editor-store"

describe("product-color-grade", () => {
  it("treats defaults as neutral (no filters)", () => {
    expect(isColorGradeNeutral(DEFAULT_COLOR_GRADE)).toBe(true)
    expect(buildProductColorFilters(DEFAULT_COLOR_GRADE)).toHaveLength(0)
  })

  it("builds brightness / contrast / saturation filters", () => {
    const grade: ProductColorGrade = {
      ...DEFAULT_COLOR_GRADE,
      brightness: 0.2,
      contrast: -0.1,
      saturation: 0.3,
    }
    const list = buildProductColorFilters(grade)
    expect(list.map((f) => f.type)).toEqual(
      expect.arrayContaining(["Brightness", "Contrast", "Saturation"])
    )
  })

  it("builds hue rotation and sharpen convolution filters", () => {
    const grade: ProductColorGrade = {
      ...DEFAULT_COLOR_GRADE,
      hue: 0.35,
      sharpness: 0.5,
    }
    const list = buildProductColorFilters(grade)
    expect(list.map((f) => f.type)).toEqual(
      expect.arrayContaining(["HueRotation", "Convolute"])
    )
  })

  it("adds a soft screen rim blend when rim is enabled", () => {
    const grade: ProductColorGrade = {
      ...DEFAULT_COLOR_GRADE,
      rimEnabled: true,
      rimStrength: 40,
      rimColor: "#ffe8c8",
    }
    const list = buildProductColorFilters(grade)
    expect(list.map((f) => f.type)).toEqual(
      expect.arrayContaining(["BlendColor"])
    )
    expect(list.map((f) => f.type)).not.toContain("Convolute")
  })

  it("builds warm / cold temperature matrices", () => {
    const warm = temperatureColorMatrix(1)
    const cold = temperatureColorMatrix(-1)
    // Warm boosts red channel gain (index 0).
    expect(warm[0]).toBeGreaterThan(cold[0])
    // Cold boosts blue channel gain (index 12).
    expect(cold[12]).toBeGreaterThan(warm[12])
  })

  it("lifts bias for positive shadows", () => {
    const lifted = toneColorMatrix(0.8, 0)
    const crushed = toneColorMatrix(-0.8, 0)
    expect(lifted[4]).toBeGreaterThan(crushed[4])
  })
})
