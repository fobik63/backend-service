"use client"

import {
  Eye,
  EyeOff,
  ImageIcon,
  Layers,
  Lock,
  Shapes,
  Sparkles,
  Type,
  Unlock,
} from "lucide-react"
import {
  useCallback,
  useMemo,
  useState,
  type DragEvent,
  type ReactNode,
} from "react"

import { Button } from "@/components/ui/button"
import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import {
  canReorderLayer,
  classifyLayer,
  LAYER_TREE_KIND_LABEL,
  layersForTree,
  layerTreeLabel,
  type LayerTreeKind,
} from "@/lib/editor/layer-meta"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"
import { cn } from "@/lib/utils"
import type { FabricObject } from "fabric"

const KIND_ICON: Record<LayerTreeKind, ReactNode> = {
  background: <ImageIcon className="size-3.5" aria-hidden />,
  product: <Sparkles className="size-3.5" aria-hidden />,
  badge: <Layers className="size-3.5" aria-hidden />,
  text: <Type className="size-3.5" aria-hidden />,
  decorative: <Shapes className="size-3.5" aria-hidden />,
}

type EngineLike = FabricObject & {
  layerId?: string
  layerRole?: string
}

function moveFabricToIndex(layerId: string, fabricIndex: number) {
  const canvas = getActiveFabricCanvas()
  if (!canvas) return
  const obj = canvas
    .getObjects()
    .find((o) => (o as EngineLike).layerId === layerId) as EngineLike | undefined
  if (!obj) return
  const withMove = canvas as typeof canvas & {
    moveObjectTo?: (object: FabricObject, index: number) => unknown
  }
  if (typeof withMove.moveObjectTo === "function") {
    withMove.moveObjectTo(obj, fabricIndex)
    canvas.requestRenderAll()
  }
}

function pinBackgroundFabric() {
  const canvas = getActiveFabricCanvas()
  if (!canvas) return
  const bg = canvas
    .getObjects()
    .find((o) => (o as EngineLike).layerRole === "background")
  if (!bg) return
  const withMove = canvas as typeof canvas & {
    moveObjectTo?: (object: FabricObject, index: number) => unknown
  }
  if (typeof withMove.moveObjectTo === "function") {
    withMove.moveObjectTo(bg, 0)
  }
  bg.set({
    selectable: false,
    evented: false,
    lockMovementX: true,
    lockMovementY: true,
    lockRotation: true,
    lockScalingX: true,
    lockScalingY: true,
  })
  canvas.requestRenderAll()
}

function LayerTreeRow({
  layer,
  selected,
  onSelect,
  onToggleVisible,
  onToggleLocked,
  draggable,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  isDragOver,
}: {
  layer: CanvasLayer
  selected: boolean
  onSelect: () => void
  onToggleVisible: () => void
  onToggleLocked: () => void
  draggable: boolean
  onDragStart: (e: DragEvent) => void
  onDragOver: (e: DragEvent) => void
  onDrop: (e: DragEvent) => void
  onDragEnd: () => void
  isDragOver: boolean
}) {
  const { t } = useI18n()
  const kind = classifyLayer(layer)
  const label = layerTreeLabel(layer)
  const kindLabel = LAYER_TREE_KIND_LABEL[kind]
  const isBg = kind === "background"
  const hidden = layer.visible === false

  return (
    <li
      draggable={draggable}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={cn(
        "group flex items-center gap-1.5 rounded-lg border px-1.5 py-1 transition-colors",
        selected
          ? "border-copper/40 bg-copper/10"
          : "border-transparent hover:border-white/10 hover:bg-white/[0.04]",
        isDragOver && "border-copper/50 bg-copper/15",
        hidden && "opacity-50",
        draggable && "cursor-grab active:cursor-grabbing"
      )}
    >
      <button
        type="button"
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring/50"
        )}
        onClick={onSelect}
        aria-pressed={selected}
      >
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] text-muted-foreground",
            selected && "text-copper"
          )}
          title={kindLabel}
        >
          {KIND_ICON[kind]}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-foreground">
            {label}
          </span>
          <span className="block truncate text-[10px] text-muted-foreground">
            {kindLabel}
          </span>
        </span>
      </button>

      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          className="size-7 text-muted-foreground hover:text-foreground"
          title={
            hidden ? t("editor.layerShow") : t("editor.layerHide")
          }
          aria-label={
            hidden ? t("editor.layerShow") : t("editor.layerHide")
          }
          onClick={(e) => {
            e.stopPropagation()
            onToggleVisible()
          }}
        >
          {hidden ? (
            <EyeOff className="size-3.5" aria-hidden />
          ) : (
            <Eye className="size-3.5" aria-hidden />
          )}
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          className="size-7 text-muted-foreground hover:text-foreground"
          title={
            layer.locked ? t("editor.layerUnlock") : t("editor.layerLock")
          }
          aria-label={
            layer.locked ? t("editor.layerUnlock") : t("editor.layerLock")
          }
          disabled={isBg}
          onClick={(e) => {
            e.stopPropagation()
            if (isBg) return
            onToggleLocked()
          }}
        >
          {layer.locked || isBg ? (
            <Lock className="size-3.5" aria-hidden />
          ) : (
            <Unlock className="size-3.5" aria-hidden />
          )}
        </Button>
      </div>
    </li>
  )
}

function LayerTreePanel() {
  const { t } = useI18n()
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const reorderLayers = useEditorStore((s) => s.reorderLayers)

  const tree = useMemo(() => layersForTree(layers), [layers])
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)

  const applyOrder = useCallback(
    (fromId: string, toId: string) => {
      if (fromId === toId) return
      const from = layers.find((l) => l.id === fromId)
      const to = layers.find((l) => l.id === toId)
      if (!from || !to) return
      if (!canReorderLayer(from) || !canReorderLayer(to)) return

      const ids = tree.map((l) => l.id)
      const fromIdx = ids.indexOf(fromId)
      const toIdx = ids.indexOf(toId)
      if (fromIdx < 0 || toIdx < 0) return

      const next = [...ids]
      next.splice(fromIdx, 1)
      next.splice(toIdx, 0, fromId)
      reorderLayers(next)

      // Immediate Fabric z-order (store rebuild follows via zIndex sceneKey).
      const interactiveBottomFirst = [...next]
        .filter((id) => {
          const layer = layers.find((l) => l.id === id)
          return layer && canReorderLayer(layer)
        })
        .reverse()
      pinBackgroundFabric()
      interactiveBottomFirst.forEach((id, index) => {
        moveFabricToIndex(id, index + 1)
      })
    },
    [layers, reorderLayers, tree]
  )

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Layers className="size-4 text-copper" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.layerTree")}
        </h3>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {t("editor.layerTreeHint")}
      </p>

      {tree.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.layerSelectHint")}
        </p>
      ) : (
        <ul className="space-y-1" aria-label={t("editor.layerTree")}>
          {tree.map((layer) => {
            const reorderable = canReorderLayer(layer)
            return (
              <LayerTreeRow
                key={layer.id}
                layer={layer}
                selected={selectedLayerId === layer.id}
                draggable={reorderable}
                isDragOver={overId === layer.id && dragId !== layer.id}
                onSelect={() => {
                  selectLayer(layer.id)
                  const canvas = getActiveFabricCanvas()
                  if (!canvas) return
                  const match = canvas
                    .getObjects()
                    .find((o) => (o as EngineLike).layerId === layer.id)
                  if (match && match.selectable !== false) {
                    canvas.setActiveObject(match)
                    canvas.requestRenderAll()
                  }
                }}
                onToggleVisible={() => {
                  updateLayer(layer.id, { visible: !layer.visible })
                }}
                onToggleLocked={() => {
                  updateLayer(layer.id, { locked: !layer.locked })
                }}
                onDragStart={(e) => {
                  if (!reorderable) {
                    e.preventDefault()
                    return
                  }
                  setDragId(layer.id)
                  e.dataTransfer.effectAllowed = "move"
                  e.dataTransfer.setData("text/plain", layer.id)
                }}
                onDragOver={(e) => {
                  if (!dragId || !reorderable) return
                  e.preventDefault()
                  e.dataTransfer.dropEffect = "move"
                  setOverId(layer.id)
                }}
                onDrop={(e) => {
                  e.preventDefault()
                  const from =
                    e.dataTransfer.getData("text/plain") || dragId || ""
                  if (from) applyOrder(from, layer.id)
                  setDragId(null)
                  setOverId(null)
                }}
                onDragEnd={() => {
                  setDragId(null)
                  setOverId(null)
                }}
              />
            )
          })}
        </ul>
      )}
    </section>
  )
}

export { LayerTreePanel }
