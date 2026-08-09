import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import {
  DEFAULT_SOFTBOX,
  useEditorStore,
} from "@/lib/store/editor-store"
import { DEFAULT_TEXT_STYLE, type CanvasLayer } from "@/types/canvas"

/** Absolute geometry / style defaults — never keep possibly corrupt values. */
export function absoluteLayerDefaults(
  layer: CanvasLayer
): Partial<CanvasLayer> {
  if (layer.type === "image") {
    return {
      x: 27,
      y: 23,
      width: 36.68,
      height: 64,
      scale: 1,
      rotation: 0,
      opacity: 1,
    }
  }
  if (layer.type === "text") {
    return {
      x: 8,
      y: 68,
      width: 84,
      scale: 1,
      rotation: 0,
      opacity: 1,
      textStyle: { ...DEFAULT_TEXT_STYLE },
    }
  }
  return {
    x: 50,
    y: 50,
    scale: 1,
    rotation: 0,
    opacity: 1,
  }
}

export function resetLayerToDefaults(layerId: string): void {
  const { layers, updateLayer } = useEditorStore.getState()
  const layer = layers.find((l) => l.id === layerId)
  if (!layer) return
  updateLayer(layerId, absoluteLayerDefaults(layer))
}

/**
 * Silent recovery after a canvas render crash (e.g. softbox slider mid-paint).
 * Resets the selected layer + softbox to safe defaults and requests a redraw.
 */
export function recoverCanvasAfterRenderError(layerId?: string | null): void {
  const store = useEditorStore.getState()

  if (store.softboxScrubbing) {
    store.setSoftboxScrubbing(false)
  }
  store.setSoftbox({ ...DEFAULT_SOFTBOX })

  const targetId = layerId ?? store.selectedLayerId
  if (targetId) {
    resetLayerToDefaults(targetId)
  }

  try {
    const canvas = getActiveFabricCanvas()
    if (canvas && typeof canvas.requestRenderAll === "function") {
      canvas.requestRenderAll()
    } else if (canvas && typeof canvas.renderAll === "function") {
      canvas.renderAll()
    }
  } catch {
    // Canvas may already be tearing down — remount will redraw.
  }
}
