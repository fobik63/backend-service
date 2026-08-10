import { describe, expect, it } from "vitest"

import {
  computeFitZoom,
  FABRIC_FIT_PADDING,
} from "@/lib/editor/fabric-viewport"

describe("computeFitZoom", () => {
  it("fits 1080×1440 into the container with padding", () => {
    const zoom = computeFitZoom(800, 1000, FABRIC_FIT_PADDING, 1080, 1440)
    const availW = 800 - FABRIC_FIT_PADDING * 2
    const availH = 1000 - FABRIC_FIT_PADDING * 2
    expect(zoom).toBeCloseTo(Math.min(availW / 1080, availH / 1440))
    expect(1080 * zoom).toBeLessThanOrEqual(availW + 0.01)
    expect(1440 * zoom).toBeLessThanOrEqual(availH + 0.01)
  })

  it("never exceeds 1× (no upscale on Fit)", () => {
    expect(computeFitZoom(4000, 4000, 40, 1080, 1440)).toBe(1)
  })
})
