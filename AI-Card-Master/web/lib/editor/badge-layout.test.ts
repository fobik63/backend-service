import { describe, expect, it } from "vitest"

import {
  BADGE_AUTO_PADDING,
  badgeTextWidthBarrier,
  buildBadgeLayoutMetrics,
} from "@/lib/editor/badge-layout"
import {
  applyBadgeStylePreset,
  BADGE_STYLE_PRESETS,
  resolveChipStrokeColor,
  resolveChipStrokeWidth,
} from "@/lib/editor/badge-styles"
import type { FeatureChipDraft } from "@/types/canvas"

const baseChip: FeatureChipDraft = {
  label: "Эко",
  bgColor: "#059669",
  borderRadius: 10,
  iconId: "icon_leaf",
  variant: "solid",
}

describe("badge auto-padding", () => {
  it("exposes marketplace Dynamic Auto-Padding constants", () => {
    expect(BADGE_AUTO_PADDING).toEqual({
      top: 12,
      right: 16,
      bottom: 12,
      left: 48,
    })
  })

  it("scales padding by CHIP_SOURCE_SCALE", () => {
    const m = buildBadgeLayoutMetrics({
      hi: 3,
      chip: baseChip,
      maxTextWidth: 400,
    })
    expect(m.padTop).toBe(36)
    expect(m.padRight).toBe(48)
    expect(m.padBottom).toBe(36)
    expect(m.padLeft).toBe(144)
  })

  it("caps text width to remaining artboard (no forced overflow minimum)", () => {
    const nearRight = badgeTextWidthBarrier({
      hi: 3,
      padLeft: 144,
      padRight: 48,
      groupLeft: 900,
      groupScaleX: 1 / 3,
      canvasWidth: 1000,
      edgeMargin: 24,
    })
    // Available plate ≈ (1000-900-24)/(1/3) = 228 source px; chrome = 192.
    expect(nearRight).toBeLessThan(200)
    expect(nearRight).toBeGreaterThan(0)
  })
})

describe("badge style presets", () => {
  it("lists the four UI presets", () => {
    expect(BADGE_STYLE_PRESETS.map((p) => p.id)).toEqual([
      "glassmorphism",
      "solidAccent",
      "darkMinimal",
      "bordered",
    ])
  })

  it("applies glassmorphism without losing label/icon", () => {
    const next = applyBadgeStylePreset(baseChip, "glassmorphism")
    expect(next.label).toBe("Эко")
    expect(next.iconId).toBe("icon_leaf")
    expect(next.variant).toBe("glass")
    expect(next.blur).toBeGreaterThan(0)
    expect(resolveChipStrokeColor(next)).toContain("255")
  })

  it("applies solid accent with optional brand color", () => {
    const next = applyBadgeStylePreset(baseChip, "solidAccent", {
      accentColor: "#E11D48",
    })
    expect(next.variant).toBe("solid")
    expect(next.bgColor).toBe("#E11D48")
    expect(next.textColor).toBe("#FFFFFF")
    expect(next.blur).toBe(0)
  })

  it("applies dark minimal and bordered strokes", () => {
    const dark = applyBadgeStylePreset(baseChip, "darkMinimal")
    expect(dark.variant).toBe("dark")
    expect(dark.bgColor).toMatch(/#|rgb/i)

    const bordered = applyBadgeStylePreset(baseChip, "bordered", {
      accentColor: "#F59E0B",
    })
    expect(bordered.variant).toBe("bordered")
    expect(bordered.bgColor).toMatch(/rgba\(0,\s*0,\s*0,\s*0\)/)
    expect(resolveChipStrokeColor(bordered)).toBe("#F59E0B")
    expect(resolveChipStrokeWidth(bordered)).toBeGreaterThanOrEqual(2)
  })
})
