/**
 * Client-side Fabric light overlay — radial soft-light wash driven by SoftboxSettings.
 * No AI API: pure Fabric.Gradient + globalCompositeOperation.
 */

import { Gradient, Rect, type Canvas as FabricCanvas, type FabricObject } from "fabric"

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/lib/constants/mock-editor"
import type { SoftboxSettings } from "@/lib/store/editor-store"

/** Warm key tint (low Kelvin). */
export const LIGHT_OVERLAY_WARM = "#FFD1A4"
/** Cool key tint (high Kelvin). */
export const LIGHT_OVERLAY_COOL = "#A4D8FF"

export type LightOverlayGeometry = {
  x1: number
  y1: number
  r1: number
  r2: number
  opacity: number
  tint: string
  enabled: boolean
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function clamp01(n: number) {
  return clamp(n, 0, 1)
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "")
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h
  const n = Number.parseInt(full, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function rgbToHex(r: number, g: number, b: number): string {
  const to = (v: number) =>
    clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")
  return `#${to(r)}${to(g)}${to(b)}`
}

function mixHex(a: string, b: string, t: number): string {
  const k = clamp01(t)
  const [ar, ag, ab] = hexToRgb(a)
  const [br, bg, bb] = hexToRgb(b)
  return rgbToHex(
    ar + (br - ar) * k,
    ag + (bg - ag) * k,
    ab + (bb - ab) * k
  )
}

function rgba(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex)
  return `rgba(${r},${g},${b},${clamp01(alpha)})`
}

/** Map Kelvin 2700 (warm) → 6500 (cool) onto #FFD1A4 … #A4D8FF. */
export function lightOverlayTintFromKelvin(colorTempK: number): string {
  const t = clamp01((colorTempK - 2700) / (6500 - 2700))
  return mixHex(LIGHT_OVERLAY_WARM, LIGHT_OVERLAY_COOL, t)
}

/**
 * Angle 0° = right, 90° = top (front), 180° = left.
 * Orbit radius scales with elevation so a high key sits closer to center.
 */
export function computeLightOverlayGeometry(
  softbox: SoftboxSettings,
  width = CANVAS_WIDTH,
  height = CANVAS_HEIGHT
): LightOverlayGeometry {
  const cx = width / 2
  const cy = height / 2
  const elevFactor = 0.55 + ((clamp(softbox.lightElevation, 10, 90) - 10) / 80) * 0.45
  const orbit = Math.min(width, height) * 0.38 * elevFactor
  const rad = (softbox.lightAngle * Math.PI) / 180
  const x1 = cx + Math.cos(rad) * orbit
  const y1 = cy - Math.sin(rad) * orbit

  // Spread 10–100% → outer radius of the softbox wash.
  const spreadPct = clamp(softbox.softboxDiffusion, 10, 100)
  const r2 = (Math.max(width, height) * spreadPct) / 100

  // Intensity 0–100% → overlay opacity (values >100 from legacy store clamp to 1).
  const opacity = softbox.enabled
    ? clamp01(softbox.intensity / 100)
    : 0

  return {
    x1,
    y1,
    r1: 0,
    r2: Math.max(1, r2),
    opacity,
    tint: lightOverlayTintFromKelvin(softbox.colorTempK),
    enabled: softbox.enabled,
  }
}

export function buildLightOverlayGradient(
  geo: LightOverlayGeometry
): Gradient<"radial"> {
  const { x1, y1, r1, r2, tint } = geo
  return new Gradient({
    type: "radial",
    gradientUnits: "pixels",
    coords: { x1, y1, x2: x1, y2: y1, r1, r2 },
    colorStops: [
      { offset: 0, color: tint },
      { offset: 0.35, color: rgba(tint, 0.55) },
      { offset: 0.72, color: rgba(tint, 0.12) },
      { offset: 1, color: rgba(tint, 0) },
    ],
  })
}

export type LightOverlayRect = Rect & {
  isLightOverlay?: boolean
}

export function isLightOverlayObject(obj: FabricObject): boolean {
  return Boolean((obj as LightOverlayRect).isLightOverlay)
}

export function findLightOverlay(canvas: FabricCanvas): LightOverlayRect | null {
  const hit = canvas.getObjects().find(isLightOverlayObject)
  return hit instanceof Rect ? (hit as LightOverlayRect) : null
}

/** Non-selectable full-bleed soft-light wash above bg + product. */
export function createLightOverlayRect(
  softbox: SoftboxSettings,
  width = CANVAS_WIDTH,
  height = CANVAS_HEIGHT
): LightOverlayRect {
  const geo = computeLightOverlayGeometry(softbox, width, height)
  const rect = new Rect({
    left: 0,
    top: 0,
    width,
    height,
    originX: "left",
    originY: "top",
    selectable: false,
    evented: false,
    hoverCursor: "default",
    objectCaching: false,
    globalCompositeOperation: "soft-light",
    fill: buildLightOverlayGradient(geo),
    opacity: geo.opacity,
    visible: geo.enabled && geo.opacity > 0,
  }) as LightOverlayRect
  rect.isLightOverlay = true
  return rect
}

/** Update gradient / opacity in place (no realloc) — call from rAF. */
export function applyLightOverlaySettings(
  overlay: LightOverlayRect,
  softbox: SoftboxSettings,
  width = CANVAS_WIDTH,
  height = CANVAS_HEIGHT
): void {
  const geo = computeLightOverlayGeometry(softbox, width, height)
  overlay.set({
    width,
    height,
    left: 0,
    top: 0,
    selectable: false,
    evented: false,
    objectCaching: false,
    globalCompositeOperation: "soft-light",
    fill: buildLightOverlayGradient(geo),
    opacity: geo.opacity,
    visible: geo.enabled && geo.opacity > 0,
    dirty: true,
  })
  overlay.setCoords()
}

/**
 * Keep the light wash stacked above background + product, under badges/text
 * and chrome overlays (safe-zones / guides).
 */
export function ensureLightOverlayStack(
  canvas: FabricCanvas,
  overlay: LightOverlayRect
): void {
  if (!canvas.getObjects().includes(overlay)) {
    canvas.add(overlay)
  }

  const live = canvas.getObjects()
  let target = 0
  for (let i = 0; i < live.length; i++) {
    const o = live[i] as FabricObject & { layerRole?: string }
    if (o === overlay) continue
    if (o.layerRole === "background" || o.layerRole === "product") {
      target = i + 1
    }
  }

  const currentIdx = live.indexOf(overlay)
  if (currentIdx >= 0 && currentIdx < target) {
    target -= 1
  }
  target = Math.max(0, Math.min(target, live.length - 1))

  const withMove = canvas as FabricCanvas & {
    moveObjectTo?: (object: FabricObject, index: number) => FabricCanvas
  }
  if (typeof withMove.moveObjectTo === "function") {
    withMove.moveObjectTo(overlay, target)
    return
  }

  if (typeof canvas.bringObjectToFront === "function") {
    canvas.bringObjectToFront(overlay)
  }
}

/**
 * Ensure a live light overlay exists and matches `softbox`.
 * Safe to call every softbox tick (rAF).
 */
export function syncFabricLightOverlay(
  canvas: FabricCanvas,
  softbox: SoftboxSettings
): LightOverlayRect {
  let overlay = findLightOverlay(canvas)
  if (!overlay) {
    overlay = createLightOverlayRect(softbox)
    canvas.add(overlay)
  } else {
    applyLightOverlaySettings(overlay, softbox)
  }
  ensureLightOverlayStack(canvas, overlay)
  return overlay
}
