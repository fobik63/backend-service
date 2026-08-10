import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { clampLayerPctPosition } from "@/lib/editor/artboard-constraints"
import { canDeleteLayer } from "@/lib/editor/layer-meta"
import { useEditorStore } from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"

const PASTE_OFFSET_PX = 15

function cloneLayer(layer: CanvasLayer): CanvasLayer {
  return {
    ...layer,
    textStyle: layer.textStyle ? { ...layer.textStyle } : undefined,
    chip: layer.chip ? { ...layer.chip } : undefined,
  }
}

let clipboard: CanvasLayer[] = []

export function getEditorClipboard(): CanvasLayer[] {
  return clipboard.map(cloneLayer)
}

export function setEditorClipboard(layers: CanvasLayer[]): void {
  clipboard = layers
    .filter(canDeleteLayer)
    .map(cloneLayer)
}

export function hasEditorClipboard(): boolean {
  return clipboard.length > 0
}

function offsetPct(): { x: number; y: number } {
  return {
    x: (PASTE_OFFSET_PX / CANVAS_WIDTH) * 100,
    y: (PASTE_OFFSET_PX / CANVAS_HEIGHT) * 100,
  }
}

function newLayerId(layer: CanvasLayer, salt: number): string {
  const prefix =
    layer.type === "text"
      ? "text"
      : layer.chip
        ? "chip"
        : layer.type === "image"
          ? "image"
          : "shape"
  return `${prefix}_${Date.now()}_${salt}`
}

function copyName(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return "Копия"
  if (/^копия/i.test(trimmed)) return trimmed
  return `Копия «${trimmed}»`
}

/** Snapshot selected layers into the app clipboard (not system clipboard). */
export function copySelectedLayers(): boolean {
  const { layers, selectedLayerId } = useEditorStore.getState()
  const targets = layers.filter(
    (layer) => layer.id === selectedLayerId && canDeleteLayer(layer)
  )
  if (targets.length === 0) return false
  setEditorClipboard(targets)
  return true
}

/** Paste clipboard layers with +15px offset; returns pasted ids. */
export function pasteClipboardLayers(): string[] {
  if (clipboard.length === 0) return []
  const { layers, replaceActivePage, selectLayer } = useEditorStore.getState()
  const maxZ = layers.reduce((m, l) => Math.max(m, l.zIndex), 0)
  const { x: dx, y: dy } = offsetPct()
  const pasted: CanvasLayer[] = clipboard.map((source, index) => ({
    ...cloneLayer(source),
    id: newLayerId(source, index),
    name: copyName(source.name),
    locked: false,
    visible: true,
    zIndex: maxZ + 1 + index,
    x: (source.x ?? 0) + dx,
    y: (source.y ?? 0) + dy,
  }))

  replaceActivePage([...layers, ...pasted])
  const last = pasted.at(-1)
  if (last) selectLayer(last.id)
  return pasted.map((layer) => layer.id)
}

/** Duplicate selection in one step (copy → paste with offset). */
export function duplicateSelectedLayers(): string[] {
  if (!copySelectedLayers()) return []
  return pasteClipboardLayers()
}

/** Nudge selected layer(s) by pixel deltas (store % geometry, artboard-clamped). */
export function nudgeSelectedLayers(dxPx: number, dyPx: number): boolean {
  if (dxPx === 0 && dyPx === 0) return false
  const store = useEditorStore.getState()
  const { selectedLayerId, layers, updateLayer, beginHistoryTransaction, commitHistoryTransaction } =
    store
  if (!selectedLayerId) return false
  const layer = layers.find((l) => l.id === selectedLayerId)
  if (!layer || layer.type === "background" || layer.locked) return false

  const dx = (dxPx / CANVAS_WIDTH) * 100
  const dy = (dyPx / CANVAS_HEIGHT) * 100
  const elW = (layer.width ?? 20) * (layer.scale ?? 1)
  const elH = (layer.height ?? 10) * (layer.scale ?? 1)
  const pos = clampLayerPctPosition(
    (layer.x ?? 0) + dx,
    (layer.y ?? 0) + dy,
    elW,
    elH
  )
  beginHistoryTransaction()
  updateLayer(layer.id, {
    x: Math.round(pos.x * 100) / 100,
    y: Math.round(pos.y * 100) / 100,
  })
  commitHistoryTransaction()
  return true
}
