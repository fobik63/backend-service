import { describe, expect, it } from "vitest"

import { clampLayerPctPosition } from "@/lib/editor/artboard-constraints"

describe("artboard-constraints", () => {
  it("clamps layer % position inside the artboard", () => {
    expect(clampLayerPctPosition(-10, -5, 20, 10)).toEqual({ x: 0, y: 0 })
    expect(clampLayerPctPosition(95, 90, 20, 10)).toEqual({ x: 80, y: 90 })
    expect(clampLayerPctPosition(50, 50, 20, 10)).toEqual({ x: 50, y: 50 })
  })

  it("allows oversized layers to sit at origin", () => {
    expect(clampLayerPctPosition(12, 8, 150, 150)).toEqual({ x: 0, y: 0 })
  })
})
