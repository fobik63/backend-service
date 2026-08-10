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

/** Marketplace product fields filled by the parser (or manually). */
export type EditorProductMeta = {
  title: string
  category: string
  brand: string
  description: string
}

export const EMPTY_PRODUCT_META: EditorProductMeta = {
  title: "",
  category: "",
  brand: "",
  description: "",
}

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
  /** AI-generated (or imported) full-bleed background for canvas layer 1. */
  backgroundPreviewUrl: string | null
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
    backgroundPreviewUrl: state.backgroundPreviewUrl,
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

/** Main card headline: prefer brand, fall back to product title. */
export function canvasHeadlineFromMeta(meta: EditorProductMeta): string {
  return meta.brand.trim() || meta.title.trim()
}

function isMainTitleLayer(layer: CanvasLayer): boolean {
  return (
    layer.type === "text" &&
    (/title$/i.test(layer.id) || layer.name === "Название")
  )
}

function withCanvasTitle(
  pageLayers: CanvasLayer[],
  headline: string
): CanvasLayer[] {
  if (!headline) return pageLayers
  return pageLayers.map((layer) =>
    isMainTitleLayer(layer) ? { ...layer, text: headline } : layer
  )
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
  /** AI / studio background image under the product cutout (layer 1). */
  backgroundPreviewUrl: string | null
  /** Bumps on every generate so Fabric rebuilds even when payload is identical. */
  generationEpoch: number
  /** Imported marketplace photos for pack / publish gallery. */
  importGalleryUrls: string[]
  /** Parsed / manual product card fields (title, brand, …). */
  productMeta: EditorProductMeta
  /** How many photos to generate in the card pack (1–20). */
  packSize: PackSize
  busyKind: EditorBusyKind
  /** 0–100 while generating; null when idle / indeterminate. */
  busyProgress: number | null
  /** True while Parser / Eye of God long-running requests are in flight. */
  aiStudioBusy: boolean
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
  /**
   * Atomically apply a generate/import result (layers + preview URLs) as one
   * undo step — avoids triple history entries and multi-scene rebuild races.
   */
  applyGenerationResult: (payload: {
    layers: CanvasLayer[]
    productPreviewUrl?: string | null
    backgroundPreviewUrl?: string | null
  }) => void
  addLayer: (layer: CanvasLayer) => void
  removeLayer: (id: string) => void
  setSoftbox: (patch: Partial<SoftboxSettings>) => void
  setProductPreviewUrl: (url: string | null) => void
  setBackgroundPreviewUrl: (url: string | null) => void
  /** Patch layer geometry without pushing history (auto-fit, sync). */
  syncLayerGeometry: (id: string, patch: Partial<CanvasLayer>) => void
  applyImportedGallery: (urls: string[]) => void
  /**
   * Apply marketplace parse result: cutout/gallery + product meta fields
   * as one undo step for the image side.
   */
  applyParsedProduct: (payload: {
    images: string[]
    title: string
    category: string
    brand: string
    description: string
  }) => void
  setProductMeta: (patch: Partial<EditorProductMeta>) => void
  setPackSize: (size: PackSize) => void
  setBusyKind: (kind: EditorBusyKind) => void
  setBusyProgress: (progress: number | null) => void
  setAiStudioBusy: (busy: boolean) => void
  beginHistoryTransaction: () => void
  commitHistoryTransaction: () => void
  undo: () => void
  redo: () => void
  /** Flush active layers into `pages` (e.g. before multi-page export). */
  commitActivePage: () => void
  /**
   * Reset editor to a clean slate.
   * `blank: true` — empty layers/history (new card `/editor/new`).
   * Default — starter pack templates.
   */
  reset: (options?: { blank?: boolean }) => void
}

let flashClearTimer: ReturnType<typeof setTimeout> | null = null

export const DEFAULT_SOFTBOX: SoftboxSettings = {
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
  backgroundPreviewUrl: null,
  generationEpoch: 0,
  importGalleryUrls: [],
  productMeta: { ...EMPTY_PRODUCT_META },
  packSize: INITIAL_PACK_SIZE,
  busyKind: "idle",
  busyProgress: null,
  aiStudioBusy: false,
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
    set((state) => ({
      projectId: project.projectId,
      pages,
      activePageIndex,
      layers,
      selectedLayerId: defaultSelectedLayerId(layers),
      flashLayerId: null,
      softbox: { ...project.softbox },
      productPreviewUrl: project.productPreviewUrl,
      backgroundPreviewUrl: project.backgroundPreviewUrl ?? null,
      importGalleryUrls: [],
      productMeta: { ...EMPTY_PRODUCT_META },
      packSize,
      // Force Fabric scene rebuild even if layer ids collide with prior project.
      generationEpoch: state.generationEpoch + 1,
      busyKind: "idle",
      busyProgress: null,
      aiStudioBusy: false,
      history: { past: [], future: [] },
      historyTransaction: null,
      canUndo: false,
      canRedo: false,
    }))
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
  applyGenerationResult: ({ layers: nextLayers, productPreviewUrl, backgroundPreviewUrl }) =>
    set((state) => {
      const layers = nextLayers.map(cloneLayer)
      const nextProduct =
        productPreviewUrl !== undefined
          ? productPreviewUrl
          : state.productPreviewUrl
      const nextBackground =
        backgroundPreviewUrl !== undefined
          ? backgroundPreviewUrl
          : state.backgroundPreviewUrl
      const history = pushPast(state.history, snapshotOf(state))
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
        selectedLayerId: defaultSelectedLayerId(layers),
        flashLayerId: null,
        productPreviewUrl: nextProduct,
        backgroundPreviewUrl: nextBackground,
        generationEpoch: state.generationEpoch + 1,
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
      const next = { ...state.softbox, ...patch }
      if (
        next.enabled === state.softbox.enabled &&
        next.lightAngle === state.softbox.lightAngle &&
        next.lightElevation === state.softbox.lightElevation &&
        next.colorTempK === state.softbox.colorTempK &&
        next.intensity === state.softbox.intensity &&
        next.softboxDiffusion === state.softbox.softboxDiffusion
      ) {
        return state
      }
      const history = state.historyTransaction
        ? state.history
        : pushPast(state.history, snapshotOf(state))
      return {
        softbox: next,
        history,
        canUndo: history.past.length > 0,
        canRedo: state.historyTransaction ? state.canRedo : false,
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
  setBackgroundPreviewUrl: (url) =>
    set((state) => {
      if (state.backgroundPreviewUrl === url) return state
      const history = pushPast(state.history, snapshotOf(state))
      return {
        backgroundPreviewUrl: url,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  syncLayerGeometry: (id, patch) =>
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
      return {
        layers,
        pages: syncActivePage(state.pages, state.activePageIndex, layers),
      }
    }),
  applyImportedGallery: (urls) =>
    set((state) => {
      const cleaned = urls
        .map((url) => url.trim())
        .filter((url) => url.length > 0)
      if (cleaned.length === 0) return state
      const packSize = clampPackSize(cleaned.length)
      const synced = syncActivePage(
        state.pages,
        state.activePageIndex,
        state.layers
      )
      const pages = resizePages(synced, packSize)
      const history = pushPast(state.history, snapshotOf(state))
      return {
        importGalleryUrls: cleaned,
        productPreviewUrl: cleaned[0] ?? state.productPreviewUrl,
        packSize,
        pages,
        activePageIndex: 0,
        layers: pages[0] ?? [],
        selectedLayerId: defaultSelectedLayerId(pages[0] ?? []),
        flashLayerId: null,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  applyParsedProduct: ({ images, title, category, brand, description }) =>
    set((state) => {
      const cleaned = images
        .map((url) => url.trim())
        .filter((url) => url.length > 0)
      const productMeta: EditorProductMeta = {
        title: title.trim(),
        category: category.trim() || "Товары",
        brand: brand.trim(),
        description: description.trim(),
      }
      const headline = canvasHeadlineFromMeta(productMeta)

      if (cleaned.length === 0) {
        const synced = syncActivePage(
          state.pages,
          state.activePageIndex,
          state.layers
        )
        const page0 = withCanvasTitle(synced[0] ?? [], headline)
        const pages = [page0, ...synced.slice(1)]
        const layers =
          state.activePageIndex === 0 ? page0 : state.layers
        const titleChanged =
          Boolean(headline) &&
          (synced[0] ?? []).some(
            (layer) => isMainTitleLayer(layer) && layer.text !== headline
          )
        if (!titleChanged) {
          return { productMeta }
        }
        const history = pushPast(state.history, snapshotOf(state))
        return {
          productMeta,
          pages,
          layers,
          selectedLayerId:
            state.activePageIndex === 0
              ? defaultSelectedLayerId(layers)
              : state.selectedLayerId,
          flashLayerId: null,
          history,
          canUndo: true,
          canRedo: false,
        }
      }

      const packSize = clampPackSize(cleaned.length)
      const synced = syncActivePage(
        state.pages,
        state.activePageIndex,
        state.layers
      )
      const resized = resizePages(synced, packSize)
      const history = pushPast(state.history, snapshotOf(state))
      const layers = withCanvasTitle(resized[0] ?? [], headline)
      const pages = [layers, ...resized.slice(1)]

      return {
        importGalleryUrls: cleaned,
        productPreviewUrl: cleaned[0] ?? state.productPreviewUrl,
        productMeta,
        packSize,
        pages,
        activePageIndex: 0,
        layers,
        selectedLayerId: defaultSelectedLayerId(layers),
        flashLayerId: null,
        history,
        canUndo: true,
        canRedo: false,
      }
    }),
  setProductMeta: (patch) =>
    set((state) => ({
      productMeta: { ...state.productMeta, ...patch },
    })),
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
  setBusyKind: (kind) =>
    set((state) => ({
      busyKind: kind,
      busyProgress: kind === "idle" ? null : state.busyProgress,
    })),
  setBusyProgress: (progress) => set({ busyProgress: progress }),
  setAiStudioBusy: (busy) => set({ aiStudioBusy: busy }),
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
        backgroundPreviewUrl: previous.backgroundPreviewUrl,
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
        backgroundPreviewUrl: next.backgroundPreviewUrl,
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
  reset: (options) => {
    const blank = options?.blank === true
    const pages = blank
      ? Array.from({ length: INITIAL_PACK_SIZE }, () => [] as CanvasLayer[])
      : buildDefaultPackPages(INITIAL_PACK_SIZE)
    const layers = pages[0] ?? []
    set((state) => ({
      pages,
      activePageIndex: 0,
      layers,
      selectedLayerId: blank ? null : defaultSelectedLayerId(layers),
      flashLayerId: null,
      zoomMode: "fit",
      softbox: DEFAULT_SOFTBOX,
      productPreviewUrl: blank ? null : DEFAULT_PRODUCT_CUTOUT,
      backgroundPreviewUrl: null,
      // Bump epoch on blank so Fabric rebuilds even when scene payload is empty.
      generationEpoch: blank ? state.generationEpoch + 1 : 0,
      importGalleryUrls: [],
      productMeta: { ...EMPTY_PRODUCT_META },
      packSize: INITIAL_PACK_SIZE,
      busyKind: "idle",
      busyProgress: null,
      aiStudioBusy: false,
      projectId: null,
      history: { past: [], future: [] },
      historyTransaction: null,
      canUndo: false,
      canRedo: false,
    }))
  },
}))

export type { EditorBusyKind }
