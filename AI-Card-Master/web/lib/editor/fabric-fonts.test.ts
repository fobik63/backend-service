import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ensureEditorFontLoaded,
  normalizeEditorFontFamily,
  resolveFabricFontFamily,
} from "@/lib/editor/fabric-fonts"

describe("resolveFabricFontFamily", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("falls back to named family when CSS var is empty", () => {
    vi.stubGlobal("document", {
      documentElement: {},
      fonts: undefined,
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: () => "",
    }))
    expect(resolveFabricFontFamily("Montserrat")).toContain("Montserrat")
  })

  it("prefers next/font CSS variable value when present", () => {
    vi.stubGlobal("document", {
      documentElement: {},
      fonts: undefined,
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: (name: string) =>
        name === "--font-inter" ? "__Inter_abc, __Inter_Fallback_abc" : "",
    }))
    const family = resolveFabricFontFamily("Inter")
    expect(family.startsWith("__Inter_abc")).toBe(true)
    expect(family).toContain("Inter")
  })

  it("resolves marketplace Cyrillic fonts", () => {
    vi.stubGlobal("document", {
      documentElement: {},
      fonts: undefined,
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: (name: string) =>
        name === "--font-unbounded" ? "__Unbounded_x" : "",
    }))
    expect(resolveFabricFontFamily("Unbounded")).toContain("__Unbounded_x")
    expect(resolveFabricFontFamily("Cera Pro")).toContain("Cera Pro")
    expect(resolveFabricFontFamily("Oswald")).toContain("Oswald")
    expect(resolveFabricFontFamily("Russo One")).toContain("Russo One")
  })
})

describe("normalizeEditorFontFamily", () => {
  it("keeps known marketplace fonts", () => {
    expect(normalizeEditorFontFamily("Oswald")).toBe("Oswald")
    expect(normalizeEditorFontFamily("Cera Pro")).toBe("Cera Pro")
  })

  it("maps legacy fonts to Inter", () => {
    expect(normalizeEditorFontFamily("Roboto")).toBe("Inter")
    expect(normalizeEditorFontFamily("Space Grotesk")).toBe("Inter")
  })
})

describe("ensureEditorFontLoaded", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("calls document.fonts.load before resolving", async () => {
    const load = vi.fn(async () => [])
    vi.stubGlobal("document", {
      documentElement: {},
      fonts: {
        ready: Promise.resolve(),
        load,
      },
    })
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: () => "__Inter_test",
    }))

    const family = await ensureEditorFontLoaded("Inter", {
      sizePx: 32,
      weight: 700,
    })
    expect(family).toContain("__Inter_test")
    expect(load).toHaveBeenCalled()
    const call = load.mock.calls.at(0) as unknown as [string] | undefined
    expect(String(call?.[0] ?? "")).toContain("700")
    expect(String(call?.[0] ?? "")).toContain("32px")
  })
})
