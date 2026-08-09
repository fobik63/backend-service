import { describe, expect, it } from "vitest"

import {
  boundsFromRect,
  canvasBounds,
  snapMoveToTargets,
} from "@/lib/editor/smart-guides"

describe("smart guides", () => {
  it("snaps badge center to product center", () => {
    const product = boundsFromRect({
      left: 400,
      top: 500,
      width: 280,
      height: 400,
    })
    // Badge almost centered on product; center↔center is nearest like-align.
    const badge = boundsFromRect({
      left: 505,
      top: 680,
      width: 120,
      height: 40,
    })
    const result = snapMoveToTargets(badge, [product], 48)
    expect(result.dx).toBeCloseTo(product.centerX - badge.centerX, 5)
    expect(result.dy).toBe(0)
    expect(
      result.guides.some(
        (g) => g.orientation === "vertical" && g.position === product.centerX
      )
    ).toBe(true)
  })

  it("snaps to canvas horizontal center", () => {
    const canvas = canvasBounds(1080, 1440)
    const chip = boundsFromRect({
      left: 530,
      top: 100,
      width: 40,
      height: 40,
    })
    const result = snapMoveToTargets(chip, [canvas], 10)
    expect(result.dx).toBeCloseTo(canvas.centerX - chip.centerX, 5)
    expect(
      result.guides.some(
        (g) => g.orientation === "vertical" && g.position === canvas.centerX
      )
    ).toBe(true)
  })

  it("does not snap when outside threshold", () => {
    const product = boundsFromRect({
      left: 0,
      top: 0,
      width: 100,
      height: 100,
    })
    const far = boundsFromRect({
      left: 400,
      top: 400,
      width: 50,
      height: 50,
    })
    const result = snapMoveToTargets(far, [product], 8)
    expect(result.dx).toBe(0)
    expect(result.dy).toBe(0)
    expect(result.guides).toHaveLength(0)
  })
})
