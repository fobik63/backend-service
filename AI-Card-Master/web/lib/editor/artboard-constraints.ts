/**
 * Keep Fabric objects inside the artboard (CANVAS_WIDTH × CANVAS_HEIGHT).
 * Shared by drag gestures and arrow-key nudge.
 */

import type { FabricObject } from "fabric"

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/lib/constants/mock-editor"

export type ArtboardConstraintFlags = {
  layerRole?: string
  isSoftbox?: boolean
  isLightOverlay?: boolean
  isChipInlineEditor?: boolean
  isProductAoShadow?: boolean
  isProductCastShadow?: boolean
  isSmartGuide?: boolean
  isSafeZoneOverlay?: boolean
}

function shouldSkipConstraint(obj: FabricObject): boolean {
  const engine = obj as FabricObject & ArtboardConstraintFlags
  if (engine.isSmartGuide || engine.isSafeZoneOverlay) return true
  if (engine.layerRole === "background") return true
  if (engine.isSoftbox || engine.isChipInlineEditor) return true
  if (engine.isLightOverlay) return true
  if (engine.isProductAoShadow || engine.isProductCastShadow) return true
  return false
}

/**
 * Clamp an object's axis-aligned bounding box inside the artboard.
 * Only adjusts left/top — never scale/angle.
 */
export function constrainObjectToArtboard(obj: FabricObject): void {
  if (shouldSkipConstraint(obj)) return

  obj.setCoords()
  const br = obj.getBoundingRect()
  let dx = 0
  let dy = 0

  if (br.left < 0) {
    dx = -br.left
  } else if (br.left + br.width > CANVAS_WIDTH) {
    dx = CANVAS_WIDTH - (br.left + br.width)
  }

  if (br.top < 0) {
    dy = -br.top
  } else if (br.top + br.height > CANVAS_HEIGHT) {
    dy = CANVAS_HEIGHT - (br.top + br.height)
  }

  if (dx === 0 && dy === 0) return

  obj.set({
    left: (obj.left ?? 0) + dx,
    top: (obj.top ?? 0) + dy,
  })
  obj.setCoords()
}

/** Clamp store % geometry so the layer AABB stays on the artboard. */
export function clampLayerPctPosition(
  x: number,
  y: number,
  elW: number,
  elH: number
): { x: number; y: number } {
  const maxX = Math.max(0, 100 - Math.max(0, elW))
  const maxY = Math.max(0, 100 - Math.max(0, elH))
  return {
    x: Math.min(maxX, Math.max(0, x)),
    y: Math.min(maxY, Math.max(0, y)),
  }
}
