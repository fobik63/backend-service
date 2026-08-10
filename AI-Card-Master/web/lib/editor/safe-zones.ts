/**
 * Marketplace safe-zone masks (Wildberries 3:4 / Ozon 1:1) + AABB overlap checks.
 * Rects are in artboard pixels (CANVAS_WIDTH × CANVAS_HEIGHT).
 */

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import type { AxisAlignedBounds } from "@/lib/editor/smart-guides"
import { boundsFromRect } from "@/lib/editor/smart-guides"

export type SafeZoneMask = "off" | "wb" | "ozon"

export type SafeZoneId =
  | "wb-bottom-bar"
  | "wb-top-right"
  | "wb-top-left"
  | "ozon-cart"
  | "ozon-discount"
  | "ozon-top-bar"

export type SafeZoneWarningKey =
  | "safeZoneWarnWbCart"
  | "safeZoneWarnWbFavorite"
  | "safeZoneWarnWbRating"
  | "safeZoneWarnOzonCart"
  | "safeZoneWarnOzonDiscount"
  | "safeZoneWarnOzonTop"

export type SafeZoneDef = {
  id: SafeZoneId
  /** Semi-transparent fill for the Fabric overlay rect. */
  fill: string
  left: number
  top: number
  width: number
  height: number
  /** i18n key under `editor.*` for the sidebar warning. */
  warningKey: SafeZoneWarningKey
}

export type SafeZoneWarning = {
  zoneId: SafeZoneId
  warningKey: SafeZoneWarningKey
}

/** Top-aligned 1:1 crop inside the 3:4 artboard (Ozon square listing). */
export function ozonSquareFrame(
  canvasW = CANVAS_WIDTH,
  canvasH = CANVAS_HEIGHT
): { left: number; top: number; width: number; height: number } {
  const side = Math.min(canvasW, canvasH)
  return {
    left: Math.round((canvasW - side) / 2),
    top: 0,
    width: side,
    height: side,
  }
}

function wbZones(w: number, h: number): SafeZoneDef[] {
  return [
    {
      id: "wb-bottom-bar",
      // Bottom panel: price, discount chip, cart — lower 18% of height.
      fill: "rgba(196, 30, 90, 0.38)",
      left: 0,
      top: Math.round(h * 0.82),
      width: w,
      height: Math.round(h * 0.18),
      warningKey: "safeZoneWarnWbCart",
    },
    {
      id: "wb-top-right",
      // Promo badge, favorites heart, share.
      fill: "rgba(124, 58, 237, 0.36)",
      left: Math.round(w * 0.72),
      top: 0,
      width: Math.round(w * 0.28),
      height: Math.round(h * 0.14),
      warningKey: "safeZoneWarnWbFavorite",
    },
    {
      id: "wb-top-left",
      // Rating / brand chip.
      fill: "rgba(168, 85, 247, 0.34)",
      left: 0,
      top: 0,
      width: Math.round(w * 0.32),
      height: Math.round(h * 0.1),
      warningKey: "safeZoneWarnWbRating",
    },
  ]
}

function ozonZones(w: number, h: number): SafeZoneDef[] {
  const frame = ozonSquareFrame(w, h)
  const { left: fx, top: fy, width: s } = frame
  return [
    {
      id: "ozon-top-bar",
      // Features / points strip along the top of the square.
      fill: "rgba(37, 99, 235, 0.34)",
      left: fx,
      top: fy,
      width: s,
      height: Math.round(s * 0.1),
      warningKey: "safeZoneWarnOzonTop",
    },
    {
      id: "ozon-cart",
      // Green add-to-cart control, bottom-right.
      fill: "rgba(5, 150, 105, 0.42)",
      left: fx + Math.round(s * 0.78),
      top: fy + Math.round(s * 0.78),
      width: Math.round(s * 0.2),
      height: Math.round(s * 0.2),
      warningKey: "safeZoneWarnOzonCart",
    },
    {
      id: "ozon-discount",
      // Discount / installment badge, bottom-left.
      fill: "rgba(234, 88, 12, 0.38)",
      left: fx + Math.round(s * 0.02),
      top: fy + Math.round(s * 0.82),
      width: Math.round(s * 0.36),
      height: Math.round(s * 0.16),
      warningKey: "safeZoneWarnOzonDiscount",
    },
  ]
}

export function getSafeZones(
  mask: SafeZoneMask,
  canvasW = CANVAS_WIDTH,
  canvasH = CANVAS_HEIGHT
): SafeZoneDef[] {
  if (mask === "wb") return wbZones(canvasW, canvasH)
  if (mask === "ozon") return ozonZones(canvasW, canvasH)
  return []
}

export function aabbIntersects(
  a: AxisAlignedBounds,
  b: AxisAlignedBounds
): boolean {
  return (
    a.left < b.right &&
    a.right > b.left &&
    a.top < b.bottom &&
    a.bottom > b.top
  )
}

export function zoneToBounds(zone: SafeZoneDef): AxisAlignedBounds {
  return boundsFromRect({
    left: zone.left,
    top: zone.top,
    width: zone.width,
    height: zone.height,
  })
}

/**
 * AABB collision: returns every dangerous zone that overlaps `objectBounds`.
 */
export function detectSafeZoneCollisions(
  mask: SafeZoneMask,
  objectBounds: AxisAlignedBounds,
  canvasW = CANVAS_WIDTH,
  canvasH = CANVAS_HEIGHT
): SafeZoneWarning[] {
  if (mask === "off") return []
  const zones = getSafeZones(mask, canvasW, canvasH)
  const hits: SafeZoneWarning[] = []
  for (const zone of zones) {
    if (aabbIntersects(objectBounds, zoneToBounds(zone))) {
      hits.push({ zoneId: zone.id, warningKey: zone.warningKey })
    }
  }
  return hits
}

/** Stable signature so store updates can be skipped when unchanged. */
export function warningsSignature(warnings: SafeZoneWarning[]): string {
  return warnings
    .map((w) => w.zoneId)
    .sort()
    .join("|")
}
