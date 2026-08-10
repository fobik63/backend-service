"use client"

import { useEffect } from "react"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import {
  clampLayerPctPosition,
  constrainObjectToArtboard,
} from "@/lib/editor/artboard-constraints"
import {
  copySelectedLayers,
  duplicateSelectedLayers,
  nudgeSelectedLayers,
  pasteClipboardLayers,
} from "@/lib/editor/editor-clipboard"
import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import { canDeleteLayer } from "@/lib/editor/layer-meta"
import { useEditorStore } from "@/lib/store/editor-store"
import type { FabricObject } from "fabric"

type EngineLike = FabricObject & {
  layerId?: string
  layerRole?: string
  isEditing?: boolean
  isSmartGuide?: boolean
  isSoftbox?: boolean
  isLightOverlay?: boolean
  isProductAoShadow?: boolean
  isProductCastShadow?: boolean
  isChipInlineEditor?: boolean
  chipPart?: string
  chipSourceScale?: number
  group?: FabricObject | null
  parent?: FabricObject | null
  hiddenTextarea?: HTMLTextAreaElement | null
  originX?: string
  originY?: string
}

/** Fabric v6 type strings (+ legacy camelCase aliases). */
function isFabricTextObjectType(type: unknown): boolean {
  return (
    type === "i-text" ||
    type === "textbox" ||
    type === "text" ||
    type === "iText" ||
    type === "IText" ||
    type === "Textbox" ||
    type === "Text"
  )
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  // Fabric.js IText/Textbox mounts a hidden textarea with data-fabric="textarea".
  if (target.getAttribute("data-fabric") === "textarea") return true
  if ((target as HTMLElement & { name?: string }).name === "fabricTextarea") {
    return true
  }
  const tag = target.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
}

function isFabricHiddenTextarea(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  return (
    el.getAttribute("data-fabric") === "textarea" ||
    (el as HTMLElement & { name?: string }).name === "fabricTextarea"
  )
}

/**
 * True when a Fabric text object is in inline edit mode (caret / selection).
 * Delete/Backspace must reach Fabric's editor — never canvas.remove().
 */
function isTextObjectEditing(obj: FabricObject | undefined | null): boolean {
  if (!obj) return false
  const engine = obj as EngineLike
  if (isFabricTextObjectType(obj.type) && engine.isEditing === true) {
    return true
  }
  if (
    isFabricTextObjectType(obj.type) &&
    engine.hiddenTextarea &&
    document.activeElement === engine.hiddenTextarea
  ) {
    return true
  }
  const nested = (
    obj as FabricObject & { getObjects?: () => FabricObject[] }
  ).getObjects?.()
  if (Array.isArray(nested)) {
    return nested.some((child) => isTextObjectEditing(child))
  }
  return false
}

function engineIsEditing(obj: FabricObject | undefined | null): boolean {
  if (!obj) return false
  if (isTextObjectEditing(obj)) return true
  const engine = obj as EngineLike
  if (engine.isEditing === true) return true
  if (engine.hiddenTextarea && document.activeElement === engine.hiddenTextarea) {
    return true
  }
  const nested = (
    obj as FabricObject & { getObjects?: () => FabricObject[] }
  ).getObjects?.()
  if (Array.isArray(nested)) {
    return nested.some((child) => engineIsEditing(child))
  }
  return false
}

function isFabricTextEditing(): boolean {
  if (isFabricHiddenTextarea(document.activeElement)) return true

  const canvas = getActiveFabricCanvas()
  if (!canvas) return false

  const textEditing = (
    canvas as unknown as {
      textEditingManager?: { target?: FabricObject | null }
    }
  ).textEditingManager?.target
  if (isTextObjectEditing(textEditing ?? null)) return true
  if (engineIsEditing(textEditing ?? null)) return true

  const active = canvas.getActiveObject()
  if (isTextObjectEditing(active)) return true
  if (engineIsEditing(active)) return true
  return canvas.getActiveObjects().some(
    (obj) => isTextObjectEditing(obj) || engineIsEditing(obj)
  )
}

function shouldIgnoreHotkey(event: KeyboardEvent): boolean {
  if (isTypingTarget(event.target)) return true
  if (isTypingTarget(document.activeElement)) return true
  if (isFabricTextEditing()) return true
  return false
}

function chipGroupOf(obj: EngineLike): EngineLike | null {
  const parent = obj.group ?? obj.parent
  if (!parent) return null
  return parent as EngineLike
}

function isChipTextPart(obj: EngineLike | undefined): boolean {
  return Boolean(obj?.chipPart === "label" || obj?.chipPart === "subtitle")
}

function isChipGroup(obj: EngineLike | undefined): boolean {
  return Boolean(obj && obj.chipSourceScale != null)
}

function pxToPct(px: number, dim: number) {
  return (px / dim) * 100
}

/** Persist Fabric left/top (after artboard clamp) back into Zustand %. */
function syncNudgeToStore(obj: EngineLike): void {
  if (!obj.layerId) return
  const store = useEditorStore.getState()
  const layer = store.layers.find((l) => l.id === obj.layerId)
  if (!layer || layer.locked) return

  const sourceScale = Math.max(1, obj.chipSourceScale ?? 1)
  const scaleAvg =
    (((obj.scaleX ?? 1) + (obj.scaleY ?? 1)) / 2) * sourceScale

  if (obj.layerRole === "product") {
    const scaledW = (obj.width ?? 0) * (obj.scaleX ?? 1)
    const scaledH = (obj.height ?? 0) * (obj.scaleY ?? 1)
    const left =
      obj.originX === "center" ? (obj.left ?? 0) - scaledW / 2 : (obj.left ?? 0)
    const top =
      obj.originY === "center" ? (obj.top ?? 0) - scaledH / 2 : (obj.top ?? 0)
    const widthPct = pxToPct(scaledW / Math.max(0.01, scaleAvg), CANVAS_WIDTH)
    const heightPct = pxToPct(scaledH / Math.max(0.01, scaleAvg), CANVAS_HEIGHT)
    const pos = clampLayerPctPosition(
      pxToPct(left, CANVAS_WIDTH),
      pxToPct(top, CANVAS_HEIGHT),
      widthPct * scaleAvg,
      heightPct * scaleAvg
    )
    store.updateLayer(obj.layerId, {
      x: Math.round(pos.x * 100) / 100,
      y: Math.round(pos.y * 100) / 100,
    })
    return
  }

  const pos = clampLayerPctPosition(
    pxToPct(obj.left ?? 0, CANVAS_WIDTH),
    pxToPct(obj.top ?? 0, CANVAS_HEIGHT),
    ((layer.width ?? 20) * (layer.scale ?? 1)),
    ((layer.height ?? 10) * (layer.scale ?? 1))
  )
  store.updateLayer(obj.layerId, {
    x: Math.round(pos.x * 100) / 100,
    y: Math.round(pos.y * 100) / 100,
  })
}

/**
 * Physical key helpers — `event.key` breaks on non-Latin layouts (RU: KeyZ → "я").
 */
function isModKey(event: KeyboardEvent, code: string, legacyKey: string): boolean {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return false
  if (event.code === code) return true
  return event.key.toLowerCase() === legacyKey
}

/** Delete active Fabric selection and sync Zustand (skips background / text edit). */
export function deleteActiveSelection(
  key: "Backspace" | "Delete" | string = "Delete"
): boolean {
  // Strict: while any text (i-text / textbox / text) isEditing, never remove layers.
  if (isFabricTextEditing()) return false

  const canvas = getActiveFabricCanvas()
  const { removeLayer, layers, selectedLayerId } = useEditorStore.getState()

  if (canvas) {
    const active = canvas.getActiveObject() as EngineLike | undefined
    if (!active) {
      // No Fabric selection — fall through to store selection below.
    } else if (
      active.isSmartGuide ||
      active.isLightOverlay ||
      active.isProductAoShadow ||
      active.isProductCastShadow ||
      active.layerRole === "background"
    ) {
      return false
    } else if (isChipTextPart(active) || active.isChipInlineEditor) {
      // Nested badge text must never delete the whole plate via Backspace/Delete.
      // Only the parent Group selection removes a badge.
      return false
    } else if (
      isTextObjectEditing(active) ||
      (isFabricTextObjectType(active.type) && active.isEditing === true)
    ) {
      // Frame-selected text (isEditing === false) may be deleted; editing caret may not.
      return false
    } else if (engineIsEditing(active)) {
      return false
    } else if (isChipGroup(active) && key === "Backspace") {
      // After a layout glitch exits nested edit, selection jumps to the Group.
      // Require Delete (not Backspace) to remove a badge — Backspace is for glyphs.
      return false
    } else {
      const targets = (canvas.getActiveObjects() as EngineLike[]).filter(
        (obj) =>
          !obj.isSmartGuide &&
          !obj.isLightOverlay &&
          !obj.isProductAoShadow &&
          !obj.isProductCastShadow &&
          obj.layerRole !== "background" &&
          // Text layers: delete object only when selected as a frame, not while editing.
          !(isFabricTextObjectType(obj.type) && obj.isEditing === true) &&
          !isTextObjectEditing(obj) &&
          obj.isEditing !== true &&
          !isChipTextPart(obj) &&
          !obj.isChipInlineEditor
      )
      if (targets.length === 0) return false

      const removeTargets: EngineLike[] = []
      const seen = new Set<EngineLike>()
      for (const obj of targets) {
        if (seen.has(obj)) continue
        // Final guard immediately before canvas.remove — never drop an editing text.
        if (
          isFabricTextObjectType(obj.type) &&
          (obj.isEditing === true || isTextObjectEditing(obj))
        ) {
          continue
        }
        seen.add(obj)
        removeTargets.push(obj)
      }
      if (removeTargets.length === 0) return false

      const layerIds = removeTargets
        .map((obj) => obj.layerId)
        .filter((id): id is string => Boolean(id))

      for (const obj of removeTargets) {
        canvas.remove(obj)
      }
      canvas.discardActiveObject()
      canvas.requestRenderAll()

      const { removeLayer, beginHistoryTransaction, commitHistoryTransaction } =
        useEditorStore.getState()
      beginHistoryTransaction()
      for (const id of layerIds) {
        removeLayer(id)
      }
      commitHistoryTransaction()
      return layerIds.length > 0
    }
  }

  if (!selectedLayerId) return false
  // Backspace on a store-selected badge (no Fabric target) — same guard.
  if (key === "Backspace") {
    const layer = layers.find((l) => l.id === selectedLayerId)
    if (layer?.chip) return false
  }
  const layer = layers.find((l) => l.id === selectedLayerId)
  if (!layer || !canDeleteLayer(layer)) return false
  removeLayer(selectedLayerId)
  return true
}

/**
 * Global editor hotkeys. Safe against HTML inputs and Fabric text editing.
 * Undo/redo use the Zustand history stack (canvas scene is a projection of it).
 */
export function useEditorHotkeys(): void {
  const undo = useEditorStore((s) => s.undo)
  const redo = useEditorStore((s) => s.redo)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (shouldIgnoreHotkey(event)) return

      // Undo / Redo — prefer event.code so RU/UA layouts still work.
      if (isModKey(event, "KeyZ", "z")) {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
        return
      }
      if (isModKey(event, "KeyY", "y")) {
        event.preventDefault()
        redo()
        return
      }

      // Copy / Paste / Duplicate
      if (isModKey(event, "KeyC", "c")) {
        if (copySelectedLayers()) event.preventDefault()
        return
      }
      if (isModKey(event, "KeyV", "v")) {
        const pasted = pasteClipboardLayers()
        if (pasted.length > 0) event.preventDefault()
        return
      }
      if (isModKey(event, "KeyD", "d")) {
        const duped = duplicateSelectedLayers()
        if (duped.length > 0) event.preventDefault()
        return
      }

      // Delete / Backspace — ignore while Fabric text isEditing so glyphs go to IText.
      if (event.key === "Delete" || event.key === "Backspace") {
        if (isFabricTextEditing()) {
          // Do not preventDefault — Fabric's hidden textarea must handle the key.
          return
        }
        if (deleteActiveSelection(event.key)) {
          event.preventDefault()
          event.stopPropagation()
        }
        return
      }

      // Arrow nudge — 1px, Shift = 10px (clamped to artboard)
      if (
        event.key === "ArrowLeft" ||
        event.key === "ArrowRight" ||
        event.key === "ArrowUp" ||
        event.key === "ArrowDown"
      ) {
        if (event.ctrlKey || event.metaKey) return
        const step = event.shiftKey ? 10 : 1
        let dx = 0
        let dy = 0
        if (event.key === "ArrowLeft") dx = -step
        if (event.key === "ArrowRight") dx = step
        if (event.key === "ArrowUp") dy = -step
        if (event.key === "ArrowDown") dy = step

        const canvas = getActiveFabricCanvas()
        const activeObjs = canvas?.getActiveObjects() ?? []
        if (canvas && activeObjs.length > 0) {
          const store = useEditorStore.getState()
          store.beginHistoryTransaction()
          let moved = false
          for (const raw of activeObjs) {
            const obj = raw as EngineLike
            if (
              obj.isSmartGuide ||
              obj.isLightOverlay ||
              obj.isProductAoShadow ||
              obj.isProductCastShadow ||
              obj.layerRole === "background" ||
              !obj.layerId
            ) {
              continue
            }
            const layer = store.layers.find((l) => l.id === obj.layerId)
            if (!layer || layer.locked) continue
            obj.set({
              left: (obj.left ?? 0) + dx,
              top: (obj.top ?? 0) + dy,
            })
            obj.setCoords()
            constrainObjectToArtboard(obj)
            syncNudgeToStore(obj)
            moved = true
          }
          const active = canvas.getActiveObject()
          active?.setCoords()
          canvas.requestRenderAll()
          store.commitHistoryTransaction()
          if (moved) {
            event.preventDefault()
          }
          return
        }

        if (nudgeSelectedLayers(dx, dy)) {
          event.preventDefault()
        }
      }
    }

    // Capture phase so we see Ctrl+Z before other UI handlers; typing guards
    // still bail out for inputs / Fabric textareas.
    window.addEventListener("keydown", onKeyDown, true)
    return () => window.removeEventListener("keydown", onKeyDown, true)
  }, [redo, undo])
}
