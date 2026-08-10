"use client"

import { useEffect, useRef } from "react"
import { toast } from "sonner"

import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import {
  buildSessionDraft,
  clearSessionDraft,
  createDebouncedSaver,
  loadSessionDraft,
  saveSessionDraft,
  sessionDraftToProjectState,
} from "@/lib/editor/session-draft"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"

/** Fabric custom props persisted alongside the editor document. */
const FABRIC_JSON_PROPERTIES = [
  "selectable",
  "id",
  "customType",
  "lockMovementX",
  "lockMovementY",
  "lockScalingX",
  "lockScalingY",
  "lockRotation",
  "layerId",
  "excludeFromExport",
] as const

const AUTOSAVE_DEBOUNCE_MS = 1000

function captureFabricJson(): unknown | undefined {
  try {
    const canvas = getActiveFabricCanvas()
    if (!canvas) return undefined
    // Fabric v6: custom props go through toObject(propertiesToInclude).
    return canvas.toObject([...FABRIC_JSON_PROPERTIES])
  } catch {
    return undefined
  }
}

/**
 * Debounced IndexedDB autosave (1s) + one-shot restore of a matching draft.
 * Call once from the editor workspace after projectId is known.
 */
export function useEditorSessionDraft(options: {
  projectId: string
  /** When false, skip restore (e.g. while remote design is still loading). */
  canRestore: boolean
  /** Prefer remote hydrate over local draft when both exist. */
  preferRemote?: boolean
}): { draftRestored: boolean } {
  const { t } = useI18n()
  const restoredRef = useRef(false)
  const draftRestoredRef = useRef(false)

  // Restore once when the surface is ready.
  useEffect(() => {
    if (!options.canRestore || restoredRef.current) return
    restoredRef.current = true

    if (options.preferRemote) {
      return
    }

    let cancelled = false
    void (async () => {
      const draft = await loadSessionDraft(options.projectId)
      if (cancelled || !draft) return
      const project = sessionDraftToProjectState(draft)
      if (!project) return
      useEditorStore.getState().loadProject(project)
      draftRestoredRef.current = true
      toast.message(t("editor.draftRestored"))
    })()

    return () => {
      cancelled = true
    }
  }, [
    options.canRestore,
    options.preferRemote,
    options.projectId,
    t,
  ])

  // Autosave on store changes (layers, softbox, format, previews…).
  useEffect(() => {
    const persist = async () => {
      const state = useEditorStore.getState()
      // Skip empty brand-new blanks with no content.
      const hasContent =
        Boolean(state.productPreviewUrl) ||
        Boolean(state.backgroundPreviewUrl) ||
        state.pages.some((page) =>
          page.some((layer) => layer.type !== "background")
        )
      if (!hasContent && state.history.past.length === 0) return

      const draft = buildSessionDraft({
        projectId: state.projectId ?? options.projectId,
        artboardFormatId: state.artboardFormatId,
        canvasWidth: state.canvasWidth,
        canvasHeight: state.canvasHeight,
        pages: state.pages,
        activePageIndex: state.activePageIndex,
        productPreviewUrl: state.productPreviewUrl,
        backgroundPreviewUrl: state.backgroundPreviewUrl,
        softbox: state.softbox,
        colorGrade: state.colorGrade,
        backgroundColorGrade: state.backgroundColorGrade,
        fabricJson: captureFabricJson(),
      })
      await saveSessionDraft(draft)
    }

    const saver = createDebouncedSaver(AUTOSAVE_DEBOUNCE_MS, persist)

    const unsubscribe = useEditorStore.subscribe((state, prev) => {
      if (
        state.pages === prev.pages &&
        state.layers === prev.layers &&
        state.softbox === prev.softbox &&
        state.colorGrade === prev.colorGrade &&
        state.backgroundColorGrade === prev.backgroundColorGrade &&
        state.productPreviewUrl === prev.productPreviewUrl &&
        state.backgroundPreviewUrl === prev.backgroundPreviewUrl &&
        state.activePageIndex === prev.activePageIndex &&
        state.packSize === prev.packSize &&
        state.artboardFormatId === prev.artboardFormatId &&
        state.canvasWidth === prev.canvasWidth &&
        state.canvasHeight === prev.canvasHeight
      ) {
        return
      }
      saver.schedule()
    })

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        void saver.flush()
      }
    }
    const onBeforeUnload = () => {
      void saver.flush()
    }
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("beforeunload", onBeforeUnload)

    return () => {
      unsubscribe()
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("beforeunload", onBeforeUnload)
      // Cancel pending debounce only — do not force-save on unmount
      // (successful remote save clears the draft and must stay cleared).
      saver.cancel()
    }
  }, [options.projectId])

  return { draftRestored: draftRestoredRef.current }
}

export async function discardEditorSessionDraft(
  projectId: string | null
): Promise<void> {
  await clearSessionDraft(projectId)
}
