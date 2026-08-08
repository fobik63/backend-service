"use client"

import { create } from "zustand"

import { MOCK_EDITOR_LAYERS } from "@/lib/constants/mock-editor"
import type { PackSize } from "@/lib/export/card-pack"
import type { CanvasLayer } from "@/types/canvas"

export type EditorZoomMode = "50" | "100" | "fit"

export const PACK_SIZE_OPTIONS: PackSize[] = [1, 3, 5]

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

type EditorState = {
  projectId: string | null
  layers: CanvasLayer[]
  selectedLayerId: string | null
  /** Briefly pulse a layer on canvas (e.g. existing badge re-click). */
  flashLayerId: string | null
  zoomMode: EditorZoomMode
  softbox: SoftboxSettings
  /** Local product preview (blob / CDN URL) shown on canvas. */
  productPreviewUrl: string | null
  /** How many photos to generate in the card pack (1 / 3 / 5). */
  packSize: PackSize
  busyKind: EditorBusyKind
  setProjectId: (id: string) => void
  selectLayer: (id: string | null) => void
  flashLayer: (id: string) => void
  setZoomMode: (mode: EditorZoomMode) => void
  updateLayer: (id: string, patch: Partial<CanvasLayer>) => void
  addLayer: (layer: CanvasLayer) => void
  removeLayer: (id: string) => void
  setSoftbox: (patch: Partial<SoftboxSettings>) => void
  setProductPreviewUrl: (url: string | null) => void
  setPackSize: (size: PackSize) => void
  setBusyKind: (kind: EditorBusyKind) => void
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

export const useEditorStore = create<EditorState>((set, get) => ({
  projectId: null,
  layers: MOCK_EDITOR_LAYERS,
  selectedLayerId: "layer_product",
  flashLayerId: null,
  zoomMode: "fit",
  softbox: DEFAULT_SOFTBOX,
  productPreviewUrl: null,
  packSize: 5,
  busyKind: "idle",
  setProjectId: (id) => set({ projectId: id }),
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
    set((state) => ({
      layers: state.layers.map((layer) =>
        layer.id === id ? { ...layer, ...patch } : layer
      ),
    })),
  addLayer: (layer) =>
    set((state) => ({
      layers: [...state.layers, layer],
      selectedLayerId: layer.id,
    })),
  removeLayer: (id) =>
    set((state) => {
      const target = state.layers.find((layer) => layer.id === id)
      if (!target || target.type === "background") return state
      const layers = state.layers.filter((layer) => layer.id !== id)
      const selectedLayerId =
        state.selectedLayerId === id
          ? (layers.find((l) => l.id === "layer_product")?.id ??
            layers.find((l) => l.type !== "background")?.id ??
            null)
          : state.selectedLayerId
      return {
        layers,
        selectedLayerId,
        flashLayerId:
          state.flashLayerId === id ? null : state.flashLayerId,
      }
    }),
  setSoftbox: (patch) =>
    set((state) => ({ softbox: { ...state.softbox, ...patch } })),
  setProductPreviewUrl: (url) => set({ productPreviewUrl: url }),
  setPackSize: (size) => set({ packSize: size }),
  setBusyKind: (kind) => set({ busyKind: kind }),
  reset: () =>
    set({
      layers: MOCK_EDITOR_LAYERS,
      selectedLayerId: "layer_product",
      flashLayerId: null,
      zoomMode: "fit",
      softbox: DEFAULT_SOFTBOX,
      productPreviewUrl: null,
      packSize: 5,
      busyKind: "idle",
    }),
}))

export type { EditorBusyKind }
