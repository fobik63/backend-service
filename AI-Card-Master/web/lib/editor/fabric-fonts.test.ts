import { afterEach, describe, expect, it, vi } from "vitest"

import { resolveFabricFontFamily } from "@/lib/editor/fabric-fonts"

describe("resolveFabricFontFamily", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("falls back to named family when CSS var is empty", () => {
    vi.stubGlobal("document", {
      documentElement: {},
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: () => "",
    }))
    expect(resolveFabricFontFamily("Montserrat")).toContain("Montserrat")
  })

  it("prefers next/font CSS variable value when present", () => {
    vi.stubGlobal("document", {
      documentElement: {},
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: (name: string) =>
        name === "--font-inter" ? "__Inter_abc, __Inter_Fallback_abc" : "",
    }))
    const family = resolveFabricFontFamily("Inter")
    expect(family.startsWith("__Inter_abc")).toBe(true)
    expect(family).toContain("Inter")
  })
})
