import type { Canvas as FabricCanvas, Point as FabricPoint } from "fabric"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"

/** Inset around the artboard so transform handles stay on-screen (40px × 2 = 80). */
export const FABRIC_FIT_PADDING = 40

/**
 * App shell header (h-14 = 56) + editor workspace bar (h-12 = 48).
 * Used when clamping Fit height against the window.
 */
export const EDITOR_HEADER_HEIGHT = 56 + 48

/** Canvas quick bar (CanvasQuickBar) approximate height. */
export const EDITOR_TOP_TOOLBAR_HEIGHT = 52

/** Extra gap below chrome before Fit padding is applied. */
export const EDITOR_VIEWPORT_GAP = 40

export type FabricViewportFrame = {
  zoom: number
  panX: number
  panY: number
  /** Screen-space rect of the 1080×1440 artboard inside the container. */
  left: number
  top: number
  width: number
  height: number
}

/**
 * Available canvas height under top chrome:
 * `window.innerHeight - headerHeight - topToolbarHeight - 40px`.
 */
export function computeAvailableCanvasHeight(
  windowHeight: number,
  headerHeight: number = EDITOR_HEADER_HEIGHT,
  topToolbarHeight: number = EDITOR_TOP_TOOLBAR_HEIGHT,
  gap: number = EDITOR_VIEWPORT_GAP
): number {
  return Math.max(120, windowHeight - headerHeight - topToolbarHeight - gap)
}

/**
 * Zoom so the full artboard fits in the wrapper with equal padding on each side.
 * Formula: `min((availW - 80) / canvasW, (availH - 80) / canvasH)`, capped at 1×.
 */
export function computeFitZoom(
  containerWidth: number,
  containerHeight: number,
  padding: number = FABRIC_FIT_PADDING,
  artboardWidth: number = CANVAS_WIDTH,
  artboardHeight: number = CANVAS_HEIGHT
): number {
  const availW = Math.max(1, containerWidth - padding * 2)
  const availH = Math.max(1, containerHeight - padding * 2)
  const next = Math.min(availW / artboardWidth, availH / artboardHeight)
  return Math.max(0.05, Math.min(1, next))
}

/**
 * Resolve container size for Fit: prefer the host box, but never exceed the
 * chrome-aware window height so the artboard cannot draw under top bars.
 */
export function resolveFitContainerSize(
  hostWidth: number,
  hostHeight: number,
  windowHeight?: number
): { width: number; height: number } {
  const width = Math.max(1, Math.floor(hostWidth))
  let height = Math.max(1, Math.floor(hostHeight))
  if (typeof windowHeight === "number" && Number.isFinite(windowHeight)) {
    height = Math.min(height, computeAvailableCanvasHeight(windowHeight))
  }
  return { width, height }
}

/**
 * Size the Fabric element to the wrapper, apply zoom, and center the artboard.
 * Uses setZoom + absolutePan (Fabric v6: absolutePan sets translate to -point).
 */
export function applyFabricZoomView(
  canvas: FabricCanvas,
  options: {
    containerWidth: number
    containerHeight: number
    /** When omitted, Fit zoom is computed from the container + padding. */
    zoom?: number
    padding?: number
  }
): FabricViewportFrame {
  const padding = options.padding ?? FABRIC_FIT_PADDING
  const w = Math.max(1, Math.floor(options.containerWidth))
  const h = Math.max(1, Math.floor(options.containerHeight))

  canvas.setWidth(w)
  canvas.setHeight(h)

  const zoom =
    options.zoom ?? computeFitZoom(w, h, padding, CANVAS_WIDTH, CANVAS_HEIGHT)

  // Center artboard in the viewport (screen px after zoom).
  const panX = (w - CANVAS_WIDTH * zoom) / 2
  const panY = (h - CANVAS_HEIGHT * zoom) / 2

  canvas.setZoom(zoom)
  // v6 absolutePan: vpt[4] = -point.x → pass -pan to get translate = pan.
  // Construct a Point-like value without importing Fabric at module scope (SSR-safe).
  canvas.absolutePan({ x: -panX, y: -panY } as FabricPoint)
  canvas.calcOffset()
  canvas.requestRenderAll()

  return {
    zoom,
    panX,
    panY,
    left: panX,
    top: panY,
    width: CANVAS_WIDTH * zoom,
    height: CANVAS_HEIGHT * zoom,
  }
}
