import { describe, expect, it } from "vitest"

import {
  computeAvailableCanvasHeight,
  computeFitZoom,
  EDITOR_HEADER_HEIGHT,
  EDITOR_TOP_TOOLBAR_HEIGHT,
  EDITOR_VIEWPORT_GAP,
  FABRIC_FIT_PADDING,
  resolveFitContainerSize,
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

  it("matches min((w - 80) / canvasW, (h - 80) / canvasH)", () => {
    const w = 900
    const h = 1100
    const expected = Math.min((w - 80) / 1080, (h - 80) / 1440)
    expect(computeFitZoom(w, h, 40, 1080, 1440)).toBeCloseTo(expected)
  })

  it("never exceeds 1× (no upscale on Fit)", () => {
    expect(computeFitZoom(4000, 4000, 40, 1080, 1440)).toBe(1)
  })
})

describe("computeAvailableCanvasHeight", () => {
  it("subtracts header, top toolbar, and 40px gap", () => {
    const windowHeight = 1000
    expect(computeAvailableCanvasHeight(windowHeight)).toBe(
      windowHeight -
        EDITOR_HEADER_HEIGHT -
        EDITOR_TOP_TOOLBAR_HEIGHT -
        EDITOR_VIEWPORT_GAP
    )
  })
})

describe("resolveFitContainerSize", () => {
  it("clamps host height to chrome-aware available height", () => {
    const windowHeight = 900
    const available = computeAvailableCanvasHeight(windowHeight)
    const sized = resolveFitContainerSize(800, 2000, windowHeight)
    expect(sized.width).toBe(800)
    expect(sized.height).toBe(available)
  })

  it("keeps host height when it already fits under chrome", () => {
    const sized = resolveFitContainerSize(640, 400, 1200)
    expect(sized).toEqual({ width: 640, height: 400 })
  })
})
