import { describe, expect, it } from "vitest"

import {
  paintSoftboxToCanvas,
  softboxKeyPosition,
  softboxOverlayStyle,
} from "@/lib/editor/softbox"
import type { SoftboxSettings } from "@/lib/store/editor-store"

const BASE: SoftboxSettings = {
  enabled: true,
  lightAngle: 45,
  lightElevation: 55,
  colorTempK: 5500,
  intensity: 100,
  softboxDiffusion: 65,
}

describe("softbox", () => {
  it("computes key light position from angle", () => {
    const right = softboxKeyPosition({ ...BASE, lightAngle: 0 })
    const left = softboxKeyPosition({ ...BASE, lightAngle: 180 })
    expect(right.x).toBeGreaterThan(50)
    expect(left.x).toBeLessThan(50)
  })

  it("builds CSS overlay style for enabled softbox", () => {
    const style = softboxOverlayStyle(BASE)
    expect(style.backgroundImage).toEqual(expect.stringContaining("radial-gradient"))
    expect(style.backgroundImage).toEqual(expect.stringContaining("linear-gradient"))
  })

  it("builds flat CSS overlay when softbox is disabled", () => {
    const style = softboxOverlayStyle({ ...BASE, enabled: false })
    expect(style.backgroundImage).toEqual(expect.stringContaining("linear-gradient"))
  })

  it("paints softbox onto a canvas without throwing", () => {
    const canvas = document.createElement("canvas")
    canvas.width = 64
    canvas.height = 64
    expect(() => paintSoftboxToCanvas(canvas, BASE)).not.toThrow()
    expect(() =>
      paintSoftboxToCanvas(canvas, { ...BASE, enabled: false })
    ).not.toThrow()
  })
})
