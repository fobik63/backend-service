import { describe, expect, it } from "vitest"

import {
  aabbIntersects,
  detectSafeZoneCollisions,
  getSafeZones,
  ozonSquareFrame,
  warningsSignature,
} from "@/lib/editor/safe-zones"
import { boundsFromRect } from "@/lib/editor/smart-guides"

describe("safe zones", () => {
  it("returns empty zones when mask is off", () => {
    expect(getSafeZones("off")).toHaveLength(0)
  })

  it("defines WB bottom bar as lower 18% of height", () => {
    const zones = getSafeZones("wb", 1080, 1440)
    const bottom = zones.find((z) => z.id === "wb-bottom-bar")
    expect(bottom).toBeDefined()
    expect(bottom!.top).toBe(Math.round(1440 * 0.82))
    expect(bottom!.height).toBe(Math.round(1440 * 0.18))
    expect(bottom!.width).toBe(1080)
  })

  it("places Ozon zones inside a top 1:1 square", () => {
    const frame = ozonSquareFrame(1080, 1440)
    expect(frame.width).toBe(1080)
    expect(frame.height).toBe(1080)
    expect(frame.top).toBe(0)

    const zones = getSafeZones("ozon", 1080, 1440)
    expect(zones).toHaveLength(3)
    for (const z of zones) {
      expect(z.left).toBeGreaterThanOrEqual(frame.left)
      expect(z.top).toBeGreaterThanOrEqual(frame.top)
      expect(z.left + z.width).toBeLessThanOrEqual(frame.left + frame.width + 1)
      expect(z.top + z.height).toBeLessThanOrEqual(frame.top + frame.height + 1)
    }
  })

  it("detects AABB overlap with WB cart / bottom bar", () => {
    const text = boundsFromRect({
      left: 100,
      top: 1300,
      width: 200,
      height: 80,
    })
    const hits = detectSafeZoneCollisions("wb", text, 1080, 1440)
    expect(hits.some((h) => h.zoneId === "wb-bottom-bar")).toBe(true)
    expect(hits[0]?.warningKey).toBe("safeZoneWarnWbCart")
  })

  it("does not warn when text is clear of dangerous zones", () => {
    const text = boundsFromRect({
      left: 400,
      top: 600,
      width: 200,
      height: 60,
    })
    expect(detectSafeZoneCollisions("wb", text, 1080, 1440)).toHaveLength(0)
    expect(detectSafeZoneCollisions("ozon", text, 1080, 1440)).toHaveLength(0)
  })

  it("aabbIntersects is exclusive on touching edges", () => {
    const a = boundsFromRect({ left: 0, top: 0, width: 10, height: 10 })
    const b = boundsFromRect({ left: 10, top: 0, width: 10, height: 10 })
    expect(aabbIntersects(a, b)).toBe(false)
  })

  it("builds a stable warnings signature", () => {
    expect(
      warningsSignature([
        { zoneId: "wb-top-left", warningKey: "safeZoneWarnWbRating" },
        { zoneId: "wb-bottom-bar", warningKey: "safeZoneWarnWbCart" },
      ])
    ).toBe("wb-bottom-bar|wb-top-left")
  })
})
