import { describe, expect, it, vi } from "vitest"

import {
  createSoftboxSourceCanvas,
  paintSoftboxInPlace,
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

function mock2dContext(canvas: HTMLCanvasElement) {
  const ctx = {
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    createLinearGradient: vi.fn(() => ({
      addColorStop: vi.fn(),
    })),
    createRadialGradient: vi.fn(() => ({
      addColorStop: vi.fn(),
    })),
    fillStyle: "",
  }
  vi.spyOn(canvas, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D)
  return ctx
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
    mock2dContext(canvas)
    expect(paintSoftboxToCanvas(canvas, BASE)).toBe(true)
    expect(
      paintSoftboxToCanvas(canvas, { ...BASE, enabled: false })
    ).toBe(true)
  })

  it("returns false when canvas context is unavailable", () => {
    const canvas = document.createElement("canvas")
    canvas.width = 0
    canvas.height = 0
    expect(paintSoftboxToCanvas(canvas, BASE)).toBe(false)
    expect(paintSoftboxInPlace(canvas, BASE)).toBe(false)

    const sized = document.createElement("canvas")
    sized.width = 16
    sized.height = 16
    vi.spyOn(sized, "getContext").mockReturnValue(null)
    expect(paintSoftboxToCanvas(sized, BASE)).toBe(false)
  })

  it("creates a dedicated source canvas and paints in place without reallocating", () => {
    const created = createSoftboxSourceCanvas(BASE, 32, 48)
    expect(created).toBeInstanceOf(HTMLCanvasElement)
    expect(created.width).toBe(32)
    expect(created.height).toBe(48)

    mock2dContext(created)
    expect(paintSoftboxInPlace(created, { ...BASE, intensity: 40 })).toBe(true)
    expect(created.width).toBe(32)
    expect(created.height).toBe(48)
  })
})
