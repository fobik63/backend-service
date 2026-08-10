import type { CSSProperties } from "react"

import type { SoftboxSettings } from "@/lib/store/editor-store"

/** Full export / idle paint size stays native; scrubbing uses a cheaper bitmap. */
export const SOFTBOX_PREVIEW_SCALE = 0.25
/** Coalesce slider → canvas softbox paints (~1 frame @ 60fps). */
export const SOFTBOX_UPDATE_MS = 24

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function clamp01(n: number) {
  return clamp(n, 0, 1)
}

function warmthFromKelvin(k: number) {
  return clamp01((6500 - k) / (6500 - 2700))
}

export function softboxKeyPosition(softbox: SoftboxSettings): {
  x: number
  y: number
} {
  const rad = (softbox.lightAngle * Math.PI) / 180
  const elevFactor = 0.55 + ((softbox.lightElevation - 10) / 80) * 0.45
  return {
    x: 50 + Math.cos(rad) * 38 * elevFactor,
    y: 50 - Math.sin(rad) * 38 * elevFactor,
  }
}

function mixRgb(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  const k = clamp01(t)
  return [
    Math.round(a[0] + (b[0] - a[0]) * k),
    Math.round(a[1] + (b[1] - a[1]) * k),
    Math.round(a[2] + (b[2] - a[2]) * k),
  ]
}

function rgbCss([r, g, b]: [number, number, number], alpha = 1): string {
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * Paint softbox studio wash onto a 2D canvas (used as Fabric layer-1 bitmap).
 * Returns false when the 2D context is missing / canvas has no size (caller must skip redraw).
 */
export function paintSoftboxToCanvas(
  target: HTMLCanvasElement | OffscreenCanvas,
  softbox: SoftboxSettings
): boolean {
  const width = target.width
  const height = target.height
  if (width <= 0 || height <= 0) return false

  let ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null
  try {
    ctx = target.getContext("2d") as
      | CanvasRenderingContext2D
      | OffscreenCanvasRenderingContext2D
      | null
  } catch {
    return false
  }
  if (!ctx) return false

  ctx.clearRect(0, 0, width, height)

  if (!softbox.enabled) {
    const g = ctx.createLinearGradient(0, 0, width * 0.3, height)
    g.addColorStop(0, "#14171d")
    g.addColorStop(1, "#0d0f12")
    ctx.fillStyle = g
    ctx.fillRect(0, 0, width, height)
    return true
  }

  const warmth = warmthFromKelvin(softbox.colorTempK)
  const cool = mixRgb([26, 32, 48], [158, 197, 255], warmth === 0 ? 0.12 : (1 - warmth) * 0.12)
  const mid: [number, number, number] = [18, 21, 27]
  const warm = mixRgb([13, 15, 18], [245, 158, 11], warmth * 0.14)

  const base = ctx.createLinearGradient(0, 0, width * 0.25, height)
  base.addColorStop(0, rgbCss(cool))
  base.addColorStop(0.48, rgbCss(mid))
  base.addColorStop(1, rgbCss(warm))
  ctx.fillStyle = base
  ctx.fillRect(0, 0, width, height)

  const lightWarmth = warmthFromKelvin(softbox.colorTempK)
  const lightRgb = mixRgb([244, 247, 251], [255, 179, 71], lightWarmth)
  const intensity = clamp(softbox.intensity / 100, 0, 2)
  const diffusion = softbox.softboxDiffusion / 100
  const { x, y } = softboxKeyPosition(softbox)
  const kx = (x / 100) * width
  const ky = (y / 100) * height
  const fillX = width * 0.5 - (kx - width * 0.5) * 0.35
  const fillY = height * 0.5 - (ky - height * 0.5) * 0.25

  const panelR = Math.max(width, height) * (0.48 + diffusion * 0.42)
  const panel = ctx.createRadialGradient(kx, ky, 0, kx, ky, panelR)
  panel.addColorStop(0, rgbCss(lightRgb, 0.42 * intensity))
  panel.addColorStop(0.68, rgbCss(lightRgb, 0))
  ctx.fillStyle = panel
  ctx.fillRect(0, 0, width, height)

  const coreR = Math.max(width, height) * ((22 + diffusion * 38) / 100)
  const core = ctx.createRadialGradient(kx, ky, 0, kx, ky, coreR)
  core.addColorStop(0, rgbCss(mixRgb(lightRgb, [255, 255, 255], 0.35), 0.28 * intensity))
  core.addColorStop(1, rgbCss(lightRgb, 0))
  ctx.fillStyle = core
  ctx.fillRect(0, 0, width, height)

  const ambientR = Math.max(width, height) * ((70 + diffusion * 30) / 100)
  const ambient = ctx.createRadialGradient(fillX, fillY, 0, fillX, fillY, ambientR)
  ambient.addColorStop(
    0,
    rgbCss(lightRgb, 0.22 * intensity * (0.55 + diffusion * 0.45))
  )
  ambient.addColorStop(0.72, rgbCss(lightRgb, 0))
  ctx.fillStyle = ambient
  ctx.fillRect(0, 0, width, height)

  const floor = ctx.createRadialGradient(
    width * 0.5,
    height,
    0,
    width * 0.5,
    height,
    width * 0.7
  )
  floor.addColorStop(0, rgbCss(lightRgb, 0.18 * intensity))
  floor.addColorStop(0.7, rgbCss(lightRgb, 0))
  ctx.fillStyle = floor
  ctx.fillRect(0, height * 0.55, width, height * 0.45)
  return true
}

/**
 * Dedicated canvas owned by a Fabric.Image — never share with module-level buffers
 * (Fabric dispose / setElement / preview resize would corrupt a shared surface).
 */
export function createSoftboxSourceCanvas(
  softbox: SoftboxSettings,
  width: number,
  height: number
): HTMLCanvasElement {
  const canvas = document.createElement("canvas")
  canvas.width = Math.max(1, Math.round(width))
  canvas.height = Math.max(1, Math.round(height))
  paintSoftboxToCanvas(canvas, softbox)
  return canvas
}

/**
 * Paint into an existing Fabric-bound canvas without reallocating or resizing
 * (resizing clears the buffer and races with Fabric's render pass).
 */
export function paintSoftboxInPlace(
  target: HTMLCanvasElement,
  softbox: SoftboxSettings
): boolean {
  try {
    if (!target || target.width <= 0 || target.height <= 0) return false
    return paintSoftboxToCanvas(target, softbox)
  } catch {
    return false
  }
}

/** Scratch surface for export / data-URL only — must NOT be passed to FabricImage. */
let softboxPaintCanvas: HTMLCanvasElement | null = null

const softboxDataUrlCache = new Map<string, string>()

/** Drop module-level softbox buffers (call on Fabric host unmount). */
export function clearSoftboxCaches(): void {
  softboxPaintCanvas = null
  softboxDataUrlCache.clear()
}

export function getSoftboxPaintCanvas(
  width: number,
  height: number
): HTMLCanvasElement {
  const w = Math.max(1, Math.round(width))
  const h = Math.max(1, Math.round(height))
  if (!softboxPaintCanvas) {
    softboxPaintCanvas = document.createElement("canvas")
  }
  if (softboxPaintCanvas.width !== w || softboxPaintCanvas.height !== h) {
    softboxPaintCanvas.width = w
    softboxPaintCanvas.height = h
  }
  return softboxPaintCanvas
}

/**
 * Paint softbox into the export scratch canvas (never bind this to Fabric.Image).
 */
export function paintSoftboxBitmap(
  softbox: SoftboxSettings,
  width: number,
  height: number,
  options?: { preview?: boolean }
): HTMLCanvasElement {
  const scale = options?.preview ? SOFTBOX_PREVIEW_SCALE : 1
  const canvas = getSoftboxPaintCanvas(width * scale, height * scale)
  paintSoftboxToCanvas(canvas, softbox)
  return canvas
}

export function softboxToDataUrl(
  softbox: SoftboxSettings,
  width: number,
  height: number
): string {
  const key = [
    width,
    height,
    softbox.enabled ? 1 : 0,
    softbox.lightAngle,
    softbox.lightElevation,
    softbox.colorTempK,
    softbox.intensity,
    softbox.softboxDiffusion,
  ].join(":")
  const cached = softboxDataUrlCache.get(key)
  if (cached) return cached

  // Dedicated canvas so we never clobber the live Fabric softbox element.
  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  paintSoftboxToCanvas(canvas, softbox)
  const url = canvas.toDataURL("image/png")
  // Bound cache — softbox knobs are discrete enough that 24 is plenty.
  if (softboxDataUrlCache.size >= 24) {
    const oldest = softboxDataUrlCache.keys().next().value
    if (oldest !== undefined) softboxDataUrlCache.delete(oldest)
  }
  softboxDataUrlCache.set(key, url)
  return url
}

/**
 * Lightweight CSS stand-in for the softbox wash while sliders are dragging.
 * Placed under the Fabric canvas (Fabric softbox opacity → 0) — no canvas paint.
 * Never animate geometry/opacity — mount + transition:all looks like the artboard "spawns and slides".
 */
const SOFTBOX_NO_TRANSITION: CSSProperties = {
  transition: "none",
  transitionProperty: "none",
  animation: "none",
}

export function softboxOverlayStyle(softbox: SoftboxSettings): CSSProperties {
  if (!softbox.enabled) {
    return {
      ...SOFTBOX_NO_TRANSITION,
      backgroundImage: "linear-gradient(160deg, #14171d 0%, #0d0f12 100%)",
    }
  }

  const warmth = warmthFromKelvin(softbox.colorTempK)
  const cool = mixRgb([26, 32, 48], [158, 197, 255], warmth === 0 ? 0.12 : (1 - warmth) * 0.12)
  const mid: [number, number, number] = [18, 21, 27]
  const warm = mixRgb([13, 15, 18], [245, 158, 11], warmth * 0.14)
  const lightRgb = mixRgb([244, 247, 251], [255, 179, 71], warmth)
  const intensity = clamp(softbox.intensity / 100, 0, 2)
  const diffusion = softbox.softboxDiffusion / 100
  const { x, y } = softboxKeyPosition(softbox)
  const panelSize = 96 + diffusion * 84
  const coreSize = 28 + diffusion * 42
  const ambientSize = 90 + diffusion * 40

  return {
    ...SOFTBOX_NO_TRANSITION,
    backgroundColor: rgbCss(mid),
    backgroundImage: [
      `radial-gradient(circle at ${x}% ${y}%, ${rgbCss(mixRgb(lightRgb, [255, 255, 255], 0.35), 0.28 * intensity)} 0%, ${rgbCss(lightRgb, 0)} ${coreSize}%)`,
      `radial-gradient(circle at ${x}% ${y}%, ${rgbCss(lightRgb, 0.42 * intensity)} 0%, ${rgbCss(lightRgb, 0)} ${panelSize}%)`,
      `radial-gradient(circle at ${50 - (x - 50) * 0.35}% ${50 - (y - 50) * 0.25}%, ${rgbCss(lightRgb, 0.22 * intensity * (0.55 + diffusion * 0.45))} 0%, ${rgbCss(lightRgb, 0)} ${ambientSize}%)`,
      `radial-gradient(circle at 50% 100%, ${rgbCss(lightRgb, 0.18 * intensity)} 0%, ${rgbCss(lightRgb, 0)} 70%)`,
      `linear-gradient(160deg, ${rgbCss(cool)} 0%, ${rgbCss(mid)} 48%, ${rgbCss(warm)} 100%)`,
    ].join(", "),
  }
}

/**
 * Top-of-canvas CSS light wash (mix-blend) — 60fps scrub preview over product layers.
 * Complements `softboxOverlayStyle` under the canvas; alone when an AI bg covers softbox.
 */
export function softboxLightBlendStyle(softbox: SoftboxSettings): CSSProperties {
  if (!softbox.enabled) {
    return {
      ...SOFTBOX_NO_TRANSITION,
      opacity: 0,
      mixBlendMode: "normal",
      backgroundImage: "none",
      boxShadow: "none",
      filter: "none",
    }
  }

  const warmth = warmthFromKelvin(softbox.colorTempK)
  const lightRgb = mixRgb([244, 247, 251], [255, 179, 71], warmth)
  const intensity = clamp(softbox.intensity / 100, 0, 2)
  const diffusion = softbox.softboxDiffusion / 100
  const { x, y } = softboxKeyPosition(softbox)
  const panelSize = 70 + diffusion * 55
  const coreSize = 22 + diffusion * 28
  const shadowSpread = 40 + (1 - intensity / 2) * 50

  return {
    ...SOFTBOX_NO_TRANSITION,
    mixBlendMode: "soft-light",
    opacity: clamp(0.35 + intensity * 0.35, 0.2, 0.95),
    backgroundImage: [
      `radial-gradient(circle at ${x}% ${y}%, ${rgbCss(mixRgb(lightRgb, [255, 255, 255], 0.4), 0.85)} 0%, ${rgbCss(lightRgb, 0)} ${coreSize}%)`,
      `radial-gradient(circle at ${x}% ${y}%, ${rgbCss(lightRgb, 0.55)} 0%, transparent ${panelSize}%)`,
    ].join(", "),
    boxShadow: `inset ${((50 - x) / 50) * 28}px ${((y - 50) / 50) * 22}px ${shadowSpread}px rgba(0,0,0,${0.22 + (1 - intensity / 2) * 0.2})`,
    filter: `saturate(${0.9 + warmth * 0.25}) brightness(${0.92 + intensity * 0.12})`,
  }
}
