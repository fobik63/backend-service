import { describe, expect, it } from "vitest"

import {
  computeLightOverlayGeometry,
  LIGHT_OVERLAY_COOL,
  LIGHT_OVERLAY_WARM,
  lightOverlayTintFromKelvin,
} from "@/lib/editor/fabric-light-overlay"
import type { SoftboxSettings } from "@/lib/store/editor-store"

const BASE: SoftboxSettings = {
  enabled: true,
  lightAngle: 45,
  lightElevation: 55,
  colorTempK: 5500,
  intensity: 100,
  softboxDiffusion: 65,
  shadowOpacity: 70,
  shadowBlur: 22,
  aoForce: 55,
  autoShadowTint: false,
}

describe("fabric-light-overlay", () => {
  it("maps warm / cool Kelvin to the required tint endpoints", () => {
    expect(lightOverlayTintFromKelvin(2700).toUpperCase()).toBe(
      LIGHT_OVERLAY_WARM
    )
    expect(lightOverlayTintFromKelvin(6500).toUpperCase()).toBe(
      LIGHT_OVERLAY_COOL
    )
    const mid = lightOverlayTintFromKelvin(4600)
    expect(mid).not.toBe(LIGHT_OVERLAY_WARM)
    expect(mid).not.toBe(LIGHT_OVERLAY_COOL)
  })

  it("orbits gradient center from lightAngle around canvas midpoint", () => {
    const w = 1000
    const h = 1000
    const right = computeLightOverlayGeometry(
      { ...BASE, lightAngle: 0 },
      w,
      h
    )
    const left = computeLightOverlayGeometry(
      { ...BASE, lightAngle: 180 },
      w,
      h
    )
    const top = computeLightOverlayGeometry(
      { ...BASE, lightAngle: 90 },
      w,
      h
    )

    expect(right.x1).toBeGreaterThan(w / 2)
    expect(left.x1).toBeLessThan(w / 2)
    expect(top.y1).toBeLessThan(h / 2)
    expect(right.y1).toBeCloseTo(h / 2, 0)
  })

  it("maps intensity 0–100% to opacity and hides when disabled", () => {
    expect(
      computeLightOverlayGeometry({ ...BASE, intensity: 0 }).opacity
    ).toBe(0)
    expect(
      computeLightOverlayGeometry({ ...BASE, intensity: 50 }).opacity
    ).toBe(0.5)
    expect(
      computeLightOverlayGeometry({ ...BASE, intensity: 100 }).opacity
    ).toBe(1)
    expect(
      computeLightOverlayGeometry({ ...BASE, intensity: 200 }).opacity
    ).toBe(1)
    expect(
      computeLightOverlayGeometry({ ...BASE, enabled: false, intensity: 100 })
        .opacity
    ).toBe(0)
  })

  it("maps softbox diffusion 10–100% to outer radius r2", () => {
    const w = 1000
    const h = 800
    const tight = computeLightOverlayGeometry(
      { ...BASE, softboxDiffusion: 10 },
      w,
      h
    )
    const wide = computeLightOverlayGeometry(
      { ...BASE, softboxDiffusion: 100 },
      w,
      h
    )
    expect(tight.r2).toBe((Math.max(w, h) * 10) / 100)
    expect(wide.r2).toBe(Math.max(w, h))
    expect(wide.r2).toBeGreaterThan(tight.r2)
    expect(tight.r1).toBe(0)
  })
})
