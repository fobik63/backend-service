"use client"

import { create } from "zustand"

import {
  buildDefaultPackPages,
  DEFAULT_PRODUCT_CUTOUT,
  defaultSelectedLayerId,
} from "@/lib/constants/mock-editor"
import {
  clampPackSize,
  PRESET_PACK_SIZES,
  type PackSize,
} from "@/lib/export/card-pack"
import type { CanvasLayer } from "@/types/canvas"

export type EditorZoomMode = "50" | "100" | "fit"

export const PACK_SIZE_OPTIONS: PackSize[] = PRESET_PACK_SIZES

/** Parametric softbox — mirrors backend StudioLightDTO (+ enabled for UI). */
export type SoftboxSettings = {
  enabled: boolean
  /** Azimuth 0–360°: 0=right, 90=front, 180=left, 270=back. */
  lightAngle: number
  /** Elevation above horizon 10–90°. */
  lightElevation: number
  /** Color temperature in Kelvin (2700 warm – 6500 cold). */
  colorTempK: number
  /** Intensity as percent 0–200 (API multiplier ×100). */
  intensity: number
  /** Softbox diffusion / shadow softness 0–100%. */
  softboxDiffusion: number
}

type EditorBusyKind = "idle" | "generating" | "saving" | "removing-bg" | "loading-image"

type EditorSnapshot = {
  pages: CanvasLayer[][]
  activePageIndex: number
  softbox: SoftboxSettings
  productPreviewUrl: string | null
  packSize: PackSize
}

type EditorHistory = {
  past: EditorSnapshot[]
  future: EditorSnapshot[]
}

export type EditorProjectState = EditorSnapshot & {
  projectId: string
}

const HISTORY_LIMIT = 50

function cloneLayer(layer: CanvasLayer): CanvasLayer {
  return {
    ...layer,
    textStyle: layer.textStyle ? { ...layer.textStyle } : undefined,
    chip: layer.chip ? { ...layer.chip } : undefined,
  }
}

function clonePages(pages: CanvasLayer[][]): CanvasLayer[][] {
  return pages.map((page) => page.map(cloneLayer))
}

function snapshotOf(state: EditorSnapshot): EditorSnapshot {
  return {
    pages: clonePages(state.pages),
    activePageIndex: state.activePageIndex,
    softbox: { ...state.softbox },
    productPreviewUrl: state.productPreviewUrl,
    packSize: state.packSize,
  }
}

function pushPast(
  history: EditorHistory,
  snapshot: EditorSnapshot
): EditorHistory {
  return {
    past: [...history.past, snapshot].slice(-HISTORY_LIMIT),
    future: [],
  }
}

function snapshotsEqual(left: EditorSnapshot, right: EditorSnapshot): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function syncActivePage(
  pages: CanvasLayer[][],
  activePageIndex: number,
  layers: CanvasLayer[]
): CanvasLayer[][] {
  return pages.map((pageLayers, index) =>
    index === activePageIndex ? layers : pageLayers
  )
}

function resizePages(
  pages: CanvasLayer[][],
  nextSize: PackSize
): CanvasLayer[][] {
  if (pages.length === nextSize) return pages
  if (pages.length > nextSize) return pages.slice(0, nextSize)
  const extras = buildDefaultPackPages(nextSize).slice(pages.length)
  return [...pages, ...extras]
}

type EditorState = {
  projectId: string | null
  /** Editable layer stacks for every pack page (index 0 = page 1). */
  pages: CanvasLayer[][]
  /** Currently edited page index (0-based). */
  activePageIndex: number
  /** Layers of the active page (kept in sync with `pages[activePageIndex]`). */
  layers: CanvasLayer[]
  selectedLayerId: string | null
  /** Briefly pulse a layer on canvas (e.g. existing badge re-click). */
  flashLayerId: string | null
  zoomMode: EditorZoomMode
  softbox: SoftboxSettings
  /** Local product preview (blob / CDN URL) shown on canvas. */
  productPreviewUrl: string | null
  /** How many photos to generate in the card pack (1–20). */
  packSize: PackSize
  busyKind: EditorBusyKind
  history: EditorHistory
  historyTransaction: EditorSnapshot | null
  canUndo: boolean
  canRedo: boolean
  setProjectId: (id: string) => void
  loadProject: (project: EditorProjectState) => void
  setActivePageIndex: (index: number) => void
  selectLayer: (id: string | null) => void
  flashLayer: (id: string) => void
  setZoomMode: (mode: EditorZoomMode) => void
  updateLayer: (id: string, patch: Partial<CanvasLayer>) => void
  replaceActivePage: (layers: CanvasLayer[]) => void
  addLayer: (layer: CanvasLayer) => void
  removeLayer: (id: string) => void
  setSoftbox: (patch: Partial<SoftboxSettings>) => void
  setProductPreviewUrl: (url: string | null) => void
  setPackSize: (size: PackSize) => void
  setBusyKind: (kind: EditorBusyKind) => void
  beginHistoryTransaction: () => void
  commitHistoryTransaction: () => void
  undo: () => void
  redo: () => void
  /** Flush active layers into `pages` (e.g. before multi-page export). */
  commitActivePage: () => void
  reset: () => void
}

let flashClearTimer: ReturnType<typeof setTimeout> | null = null

const DEFAULT_SOFTBOX: SoftboxSettings = {
  enabled: true,
  lightAngle: 45,
  lightElevation: 55,
  colorTempK: 5500,
  intensity: 100,
  softboxDiffusion: 65,
}

const INITIAL_PACK_SIZE: PackSize = 5
const INITIAL_PAGES = buildDefaultPackPages(INITIAL_PACK_SIZE)
const INITIAL_LAYERS = INITIAL_PAGES[0] ?? []

export const useEditorStore = create<EditorState>((set, get) => ({
  projectId: null,
  pages: INITIAL_PAGES,
  activePageIndex: 0,
  layers: INITIAL_LAYERS,
  selectedLayerId: defaultSelectedLayerId(INITIAL_LAYERS),
  flashLayerId: null,
  zoomMode: "fit",
  softbox: DEFAULT_SOFTBOX,
  productPreviewUrl: DEFAULT_PRODUCT_CUTOUT,
  packSize: INITIAL_PACK_SIZE,
  busyKind: "idle",
  history: { past: [], future: [] },
  historyTransaction: null,
  canUndo: false,
  canRedo: false,
  setProjectId: (id) => set({ projectId: id }),
  loadProject: (project) => {
    const pages = clonePages(project.pages)
    const packSize = clampPackSize(project.packSize)
    const activePageIndex = Math.min(
      Math.max(0, Math.floor(project.activePageIndex)),
      Math.max(0, pages.length - 1)
    )
    const layers = pages[activePageIndex] ?? []
    set({
      projectId: project.projectId,
      pages,
      activePageIndex,
      layers,
      selectedLayerId: defaultSelectedLayerId(layers),
      flashLayerId: null,
      softbox: { ...project.softbox },
      productPreviewUrl: project.productPreviewUrl,
      packSize,
      busyKind: "idle",
      history: { past: [], future: [] },
      historyTransaction: null,
      canUndo: false,
      canRedo: false,
    })
  },
  setActivePageIndex: (index) => {
    const state = get()
    const max = Math.max(0, state.pages.length - 1)
    const nextIndex = Math.min(max, Math.max(0, Math.floor(index)))
    if (nextIndex === state.activePageIndex) return

    const pages = syncActivePage(state.pages, state.activePageIndex, state.layers)
    const layers = pages[nextIndex] ?? []
    set({
      pages,
      activePageIndex: nextIndex,
      layers,
      selectedLayerId: defaultSelectedLayerId(layers),
      flashLayerId: null,
    })
  },
  selectLayer: (id) => set({ selectedLayerId: id }),
  flashLayer: (id) => {
    if (flashClearTimer) clearTimeout(flashClearTimer)
    set({ flashLayerId: id, selectedLayerId: id })
    flashClearTimer = setTimeout(() => {
      if (get().flashLayerId === id) {
        set({ flashLayerId: null })
      }
      flashClearTimer = null
    }, 900)
  },
  setZoomMode: (mode) => set({ zoomMode: mode }),
  updateLayer: (id, patch) =>
    set((state) => {
      const layers = state.layers.map((layer) => {
        if (layer.id !== id) return layer
        return {
          ...layer,
          ...patch,
          textStyle:
            patch.textStyle !== undefined
              ? { ...layer.textStyle, ...patch.textStyle }
              : layer.textStyle,
          chip:
            patch.chip !== undefined
              ? { ...layer.chip, ...patch.chip }
              : layer.chip,
        }
      })
      const history = state.historyTransaction
        ? state.history
        : pushPast(state.history, snapshotOf(state))
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
        history,
        canUndo: history.past.length > 0,
        canRedo: false,
      }
    }),
  replaceActivePage: (nextLayers) =>
    set((state) => {
      const layers = nextLayers.map(cloneLayer)
      const history = pushPast(state.history, snapshotOf(state))
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
        selectedLayerId: defaultSelectedLayerId(layers),
        flashLayerId: null,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  addLayer: (layer) =>
    set((state) => {
      const layers = [...state.layers, layer]
      const history = pushPast(state.history, snapshotOf(state))
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
        selectedLayerId: layer.id,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  removeLayer: (id) =>
    set((state) => {
      const target = state.layers.find((layer) => layer.id === id)
      if (!target || target.type === "background") return state
      const layers = state.layers.filter((layer) => layer.id !== id)
      const selectedLayerId =
        state.selectedLayerId === id
          ? defaultSelectedLayerId(layers)
          : state.selectedLayerId
      const history = pushPast(state.history, snapshotOf(state))
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
        selectedLayerId,
        flashLayerId:
          state.flashLayerId === id ? null : state.flashLayerId,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  setSoftbox: (patch) =>
    set((state) => {
      const history = pushPast(state.history, snapshotOf(state))
      return {
        softbox: { ...state.softbox, ...patch },
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  setProductPreviewUrl: (url) =>
    set((state) => {
      if (state.productPreviewUrl === url) return state
      const history = pushPast(state.history, snapshotOf(state))
      return {
        productPreviewUrl: url,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  setPackSize: (size) =>
    set((state) => {
      const packSize = clampPackSize(size)
      const synced = syncActivePage(
        state.pages,
        state.activePageIndex,
        state.layers
      )
      const pages = resizePages(synced, packSize)
      const activePageIndex = Math.min(state.activePageIndex, packSize - 1)
      const layers = pages[activePageIndex] ?? []
      const history = pushPast(state.history, snapshotOf(state))
      return {
        packSize,
        pages,
        activePageIndex,
        layers,
        selectedLayerId:
          activePageIndex === state.activePageIndex
            ? state.selectedLayerId &&
              layers.some((l) => l.id === state.selectedLayerId)
              ? state.selectedLayerId
              : defaultSelectedLayerId(layers)
            : defaultSelectedLayerId(layers),
        flashLayerId:
          activePageIndex === state.activePageIndex
            ? state.flashLayerId
            : null,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  setBusyKind: (kind) => set({ busyKind: kind }),
  beginHistoryTransaction: () =>
    set((state) => {
      if (state.historyTransaction) return state
      return { historyTransaction: snapshotOf(state) }
    }),
  commitHistoryTransaction: () =>
    set((state) => {
      const started = state.historyTransaction
      if (!started) return state
      const current = snapshotOf(state)
      if (snapshotsEqual(started, current)) {
        return { historyTransaction: null }
      }
      const history = pushPast(state.history, started)
      return {
        history,
        historyTransaction: null,
        canUndo: true,
        canRedo: false,
      }
    }),
  undo: () =>
    set((state) => {
      const previous = state.history.past.at(-1)
      if (!previous) return state
      const current = snapshotOf(state)
      const pages = clonePages(previous.pages)
      const activePageIndex = Math.min(
        previous.activePageIndex,
        Math.max(0, pages.length - 1)
      )
      const layers = pages[activePageIndex] ?? []
      const history: EditorHistory = {
        past: state.history.past.slice(0, -1),
        future: [current, ...state.history.future].slice(0, HISTORY_LIMIT),
      }
      return {
        pages,
        activePageIndex,
        layers,
        selectedLayerId: defaultSelectedLayerId(layers),
        flashLayerId: null,
        softbox: { ...previous.softbox },
        productPreviewUrl: previous.productPreviewUrl,
        packSize: previous.packSize,
        history,
        historyTransaction: null,
        canUndo: history.past.length > 0,
        canRedo: true,
      }
    }),
  redo: () =>
    set((state) => {
      const next = state.history.future[0]
      if (!next) return state
      const current = snapshotOf(state)
      const pages = clonePages(next.pages)
      const activePageIndex = Math.min(
        next.activePageIndex,
        Math.max(0, pages.length - 1)
      )
      const layers = pages[activePageIndex] ?? []
      const history: EditorHistory = {
        past: [...state.history.past, current].slice(-HISTORY_LIMIT),
        future: state.history.future.slice(1),
      }
      return {
        pages,
        activePageIndex,
        layers,
        selectedLayerId: defaultSelectedLayerId(layers),
        flashLayerId: null,
        softbox: { ...next.softbox },
        productPreviewUrl: next.productPreviewUrl,
        packSize: next.packSize,
        history,
        historyTransaction: null,
        canUndo: true,
        canRedo: history.future.length > 0,
      }
    }),
  commitActivePage: () =>
    set((state) => ({
      pages: syncActivePage(state.pages, state.activePageIndex, state.layers),
    })),
  reset: () => {
    const pages = buildDefaultPackPages(INITIAL_PACK_SIZE)
    const layers = pages[0] ?? []
    set({
      pages,
      activePageIndex: 0,
      layers,
      selectedLayerId: defaultSelectedLayerId(layers),
      flashLayerId: null,
      zoomMode: "fit",
      softbox: DEFAULT_SOFTBOX,
      productPreviewUrl: DEFAULT_PRODUCT_CUTOUT,
      packSize: INITIAL_PACK_SIZE,
      busyKind: "idle",
      projectId: null,
      history: { past: [], future: [] },
      historyTransaction: null,
      canUndo: false,
      canRedo: false,
    })
  },
}))

export type { EditorBusyKind }
