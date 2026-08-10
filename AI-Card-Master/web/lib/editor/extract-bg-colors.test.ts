import { describe, expect, it } from "vitest"

import {
  contrastTextForBg,
  parseCssColor,
  pickHarmoniousBadgeColors,
  relativeLuminance,
  rgbToHex,
} from "@/lib/editor/extract-bg-colors"

describe("extract-bg-colors helpers", () => {
  it("parses hex and rgba", () => {
    expect(parseCssColor("#0F1115")).toEqual({ r: 15, g: 17, b: 21 })
    expect(parseCssColor("#abc")).toEqual({ r: 170, g: 187, b: 204 })
    expect(parseCssColor("rgba(15,17,21,0.55)")).toEqual({
      r: 15,
      g: 17,
      b: 21,
    })
  })

  it("formats rgb to hex", () => {
    expect(rgbToHex({ r: 15, g: 17, b: 21 })).toBe("#0F1115")
  })

  it("picks contrasting text", () => {
    expect(contrastTextForBg("#FFFFFF")).toBe("#0F1115")
    expect(contrastTextForBg("#0F1115")).toBe("#FFFFFF")
    expect(contrastTextForBg("rgba(15,17,21,0.55)")).toBe("#FFFFFF")
  })

  it("computes relative luminance for white > black", () => {
    expect(relativeLuminance({ r: 255, g: 255, b: 255 })).toBeGreaterThan(
      relativeLuminance({ r: 0, g: 0, b: 0 })
    )
  })

  it("builds glass-tinted badge colors from a palette", () => {
    const result = pickHarmoniousBadgeColors([
      "#E8F5E9",
      "#2E7D32",
      "#1B5E20",
      "#A5D6A7",
      "#FFFFFF",
    ])
    expect(result.bgColor.startsWith("rgba(")).toBe(true)
    expect(result.textColor).toBe("#FFFFFF")
  })

  it("falls back when palette is empty", () => {
    expect(pickHarmoniousBadgeColors([])).toEqual({
      bgColor: "rgba(15,17,21,0.55)",
      textColor: "#FFFFFF",
    })
  })
})
