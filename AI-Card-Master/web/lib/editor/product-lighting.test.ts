import { describe, expect, it } from "vitest"

import {
  bakeProductCastSilhouette,
  computeProductShadowParams,
  PRODUCT_LIGHTING_UPDATE_MS,
  resolveShadowTintRgb,
  sampleDarkestPixelRgb,
  SHADOW_TINT_COOL,
  SHADOW_TINT_WARM,
} from "@/lib/editor/product-lighting"
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

describe("product-lighting", () => {
  it("uses a ~1 frame debounce window", () => {
    expect(PRODUCT_LIGHTING_UPDATE_MS).toBe(16)
  })

  it("returns null when softbox is disabled", () => {
    expect(computeProductShadowParams({ ...BASE, enabled: false })).toBeNull()
  })

  it("skews cast shadow opposite the key light", () => {
    const right = computeProductShadowParams({ ...BASE, lightAngle: 0 })
    const left = computeProductShadowParams({ ...BASE, lightAngle: 180 })
    expect(right).not.toBeNull()
    expect(left).not.toBeNull()
    // Light from the right → cast shears to the left (negative skewX).
    expect(right!.cast.skewX).toBeLessThan(0)
    // Light from the left → cast shears to the right (positive skewX).
    expect(left!.cast.skewX).toBeGreaterThan(0)
  })

  it("lengthens cast shadow (higher flattenY) at low elevation", () => {
    const low = computeProductShadowParams({ ...BASE, lightElevation: 15 })
    const high = computeProductShadowParams({ ...BASE, lightElevation: 85 })
    expect(low!.cast.flattenY).toBeGreaterThan(high!.cast.flattenY)
  })

  it("maps shadowBlur to cast penumbra 0..100px", () => {
    const soft = computeProductShadowParams({
      ...BASE,
      shadowBlur: 100,
    })
    const hard = computeProductShadowParams({
      ...BASE,
      shadowBlur: 0,
    })
    expect(soft!.cast.blur).toBe(100)
    expect(hard!.cast.blur).toBe(0)
  })

  it("scales both shadow layers from shadowOpacity", () => {
    const strong = computeProductShadowParams({
      ...BASE,
      shadowOpacity: 100,
    })
    const weak = computeProductShadowParams({
      ...BASE,
      shadowOpacity: 10,
    })
    expect(strong!.cast.opacity).toBeGreaterThan(weak!.cast.opacity)
  })

  it("scales contact AO from aoForce independently", () => {
    const hard = computeProductShadowParams({ ...BASE, aoForce: 100 })
    const soft = computeProductShadowParams({ ...BASE, aoForce: 0 })
    expect(hard!.contact.opacity).toBeGreaterThan(soft!.contact.opacity)
    expect(hard!.contact.blur).toBeGreaterThanOrEqual(soft!.contact.blur)
  })

  it("uses cool shadow under warm light and warm shadow under cold light", () => {
    const warmLight = resolveShadowTintRgb({ ...BASE, colorTempK: 2700 })
    const coldLight = resolveShadowTintRgb({ ...BASE, colorTempK: 6500 })
    expect(warmLight).toEqual(SHADOW_TINT_COOL)
    expect(coldLight).toEqual(SHADOW_TINT_WARM)
  })

  it("mixes auto background tint when enabled", () => {
    const tint = resolveShadowTintRgb(
      { ...BASE, autoShadowTint: true, colorTempK: 5500 },
      [80, 40, 20]
    )
    const plain = resolveShadowTintRgb(
      { ...BASE, autoShadowTint: false, colorTempK: 5500 },
      [80, 40, 20]
    )
    expect(tint).not.toEqual(plain)
  })

  it("keeps cast falloff opaque at base and nearly transparent at tip", () => {
    const params = computeProductShadowParams(BASE)
    expect(params).not.toBeNull()
    expect(params!.cast.baseAlpha).toBeGreaterThanOrEqual(0.45)
    expect(params!.cast.baseAlpha).toBeLessThanOrEqual(0.95)
    expect(params!.cast.tipAlpha).toBeGreaterThanOrEqual(0)
    expect(params!.cast.tipAlpha).toBeLessThanOrEqual(0.1)
  })

  it("bakes a canvas matching silhouette size when blur is 0", () => {
    const src = document.createElement("canvas")
    src.width = 32
    src.height = 48
    const params = computeProductShadowParams({ ...BASE, shadowBlur: 0 })!
    const baked = bakeProductCastSilhouette(src, 32, 48, params.cast)
    expect(baked.width).toBe(32)
    expect(baked.height).toBe(48)
  })

  it("pads the bake canvas for blur when 2d context is available", () => {
    const src = document.createElement("canvas")
    src.width = 32
    src.height = 48
    if (!src.getContext("2d")) return
    const params = computeProductShadowParams({ ...BASE, shadowBlur: 10 })!
    const baked = bakeProductCastSilhouette(src, 32, 48, params.cast)
    expect(baked.width).toBeGreaterThan(32)
    expect(baked.height).toBeGreaterThan(48)
  })

  it("samples the darkest opaque pixel when 2d context is available", () => {
    const src = document.createElement("canvas")
    src.width = 4
    src.height = 4
    const ctx = src.getContext("2d")
    if (!ctx) return
    ctx.fillStyle = "rgb(200,200,200)"
    ctx.fillRect(0, 0, 4, 4)
    ctx.fillStyle = "rgb(10,20,30)"
    ctx.fillRect(1, 1, 1, 1)
    expect(sampleDarkestPixelRgb(src, 4)).toEqual([10, 20, 30])
  })
})
