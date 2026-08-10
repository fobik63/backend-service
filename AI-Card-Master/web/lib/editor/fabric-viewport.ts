import { Point, type Canvas as FabricCanvas } from "fabric"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"

/** Inset around the artboard so transform handles stay on-screen. */
export const FABRIC_FIT_PADDING = 40

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
 * Zoom so the full artboard fits in the wrapper with equal padding on each side.
 * Capped at 1 so Fit never upscales past native pixels.
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
  canvas.absolutePan(new Point(-panX, -panY))
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
