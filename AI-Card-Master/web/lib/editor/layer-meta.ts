import type { CanvasLayer, CanvasLayerType } from "@/types/canvas"

/** UI taxonomy for the Layer Tree panel (not a store type). */
export type LayerTreeKind =
  | "background"
  | "product"
  | "badge"
  | "text"
  | "decorative"

export const LAYER_TREE_KIND_LABEL: Record<LayerTreeKind, string> = {
  background: "Фон",
  product: "Товар",
  badge: "Плашка",
  text: "Текст",
  decorative: "Декоративный элемент",
}

export function classifyLayer(layer: CanvasLayer): LayerTreeKind {
  if (layer.type === "background") return "background"
  if (layer.type === "image" || layer.id === "layer_product" || /product/i.test(layer.id)) {
    return "product"
  }
  if (layer.type === "text") return "text"
  if (layer.type === "shape" && layer.chip) return "badge"
  if (layer.type === "shape") return "decorative"
  return "decorative"
}

export function layerTreeLabel(layer: CanvasLayer): string {
  const kind = classifyLayer(layer)
  if (kind === "badge" && layer.chip?.label) {
    return layer.name?.trim() || `Плашка «${layer.chip.label}»`
  }
  if (kind === "text" && layer.text?.trim()) {
    return layer.name?.trim() || layer.text.trim()
  }
  return layer.name?.trim() || LAYER_TREE_KIND_LABEL[kind]
}

/** Top of the stack first (highest zIndex). Background stays last. */
export function layersForTree(layers: CanvasLayer[]): CanvasLayer[] {
  return [...layers].sort((a, b) => {
    if (a.type === "background" && b.type !== "background") return 1
    if (b.type === "background" && a.type !== "background") return -1
    return b.zIndex - a.zIndex
  })
}

export function isBackgroundLayer(layer: CanvasLayer): boolean {
  return layer.type === "background"
}

export function canReorderLayer(layer: CanvasLayer): boolean {
  return layer.type !== "background"
}

export function canDeleteLayer(layer: CanvasLayer): boolean {
  return layer.type !== "background"
}

/** Remap zIndex from a top→bottom id list; background forced to 0. */
export function applyTreeOrder(
  layers: CanvasLayer[],
  orderedIdsTopFirst: string[]
): CanvasLayer[] {
  const byId = new Map(layers.map((layer) => [layer.id, layer]))
  const interactiveIds = orderedIdsTopFirst.filter((id) => {
    const layer = byId.get(id)
    return Boolean(layer && layer.type !== "background")
  })
  const missing = layers
    .filter(
      (layer) =>
        layer.type !== "background" && !interactiveIds.includes(layer.id)
    )
    .sort((a, b) => b.zIndex - a.zIndex)
    .map((layer) => layer.id)
  const topToBottom = [...interactiveIds, ...missing]
  const count = topToBottom.length

  return layers.map((layer) => {
    if (layer.type === "background") {
      return { ...layer, zIndex: 0, locked: true }
    }
    const idx = topToBottom.indexOf(layer.id)
    if (idx < 0) return layer
    return { ...layer, zIndex: count - idx }
  })
}

export function layerTypeIconKey(type: CanvasLayerType | LayerTreeKind): LayerTreeKind {
  if (type === "image") return "product"
  if (type === "shape") return "badge"
  if (type === "background" || type === "text" || type === "product" || type === "badge" || type === "decorative") {
    return type
  }
  return "decorative"
}
