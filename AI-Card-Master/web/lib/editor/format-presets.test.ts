import { describe, expect, it } from "vitest"

import {
  ARTBOARD_FORMAT_PRESETS,
  getArtboardPreset,
  smartScalePages,
} from "@/lib/editor/format-presets"
import type { CanvasLayer } from "@/types/canvas"

describe("format presets", () => {
  it("includes WB / Ozon / Yandex marketplace sizes", () => {
    const ids = ARTBOARD_FORMAT_PRESETS.map((p) => p.id)
    expect(ids).toContain("wb-900")
    expect(ids).toContain("wb-1500")
    expect(ids).toContain("ozon-1-1")
    expect(ids).toContain("yandex-3-4")
    expect(ids).toContain("yandex-1-1")

    expect(getArtboardPreset("ozon-1-1")).toMatchObject({
      width: 1200,
      height: 1200,
      ratio: "1:1",
    })
    expect(getArtboardPreset("wb-900")).toMatchObject({
      width: 900,
      height: 1200,
      ratio: "3:4",
    })
  })

  it("smart-scales absolute text metrics and keeps background full-bleed", () => {
    const pages: CanvasLayer[][] = [
      [
        {
          id: "bg",
          type: "background",
          name: "Фон",
          visible: true,
          locked: true,
          opacity: 1,
          zIndex: 0,
          x: 0,
          y: 0,
          width: 100,
          height: 100,
          scale: 1,
        },
        {
          id: "title",
          type: "text",
          name: "Title",
          visible: true,
          locked: false,
          opacity: 1,
          zIndex: 2,
          x: 10,
          y: 20,
          width: 80,
          height: 10,
          scale: 1,
          text: "Hello",
          textStyle: {
            fontFamily: "Inter",
            fontSize: 48,
            fontWeight: 700,
            color: "#fff",
            strokeWidth: 2,
            strokeColor: "#000",
            shadowEnabled: false,
            shadowColor: "#000",
            shadowBlur: 0,
            shadowOffsetX: 0,
            shadowOffsetY: 0,
          },
        },
      ],
    ]

    const scaled = smartScalePages(
      pages,
      { width: 1080, height: 1440 },
      { width: 1200, height: 1200 }
    )
    const bg = scaled[0]![0]!
    const title = scaled[0]![1]!

    expect(bg.width).toBe(100)
    expect(bg.height).toBe(100)
    expect(title.textStyle?.fontSize).not.toBe(48)
    expect(title.textStyle?.fontSize).toBeGreaterThan(8)
  })

  it("is a no-op when artboard size is unchanged", () => {
    const pages: CanvasLayer[][] = [
      [
        {
          id: "bg",
          type: "background",
          name: "Фон",
          visible: true,
          locked: true,
          opacity: 1,
          zIndex: 0,
        },
      ],
    ]
    const size = { width: 1080, height: 1440 }
    expect(smartScalePages(pages, size, size)).toBe(pages)
  })
})
