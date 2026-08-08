"use client"

import { create } from "zustand"

import { MOCK_EDITOR_LAYERS } from "@/lib/constants/mock-editor"
import type { CanvasLayer } from "@/types/canvas"

export type EditorZoomMode = "50" | "100" | "fit"

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
  zoomMode: EditorZoomMode
  softbox: SoftboxSettings
  /** Local product preview (blob / CDN URL) shown on canvas. */
  productPreviewUrl: string | null
  busyKind: EditorBusyKind
  setProjectId: (id: string) => void
  selectLayer: (id: string | null) => void
  setZoomMode: (mode: EditorZoomMode) => void
  updateLayer: (id: string, patch: Partial<CanvasLayer>) => void
  addLayer: (layer: CanvasLayer) => void
  setSoftbox: (patch: Partial<SoftboxSettings>) => void
  setProductPreviewUrl: (url: string | null) => void
  setBusyKind: (kind: EditorBusyKind) => void
  reset: () => void
}

const DEFAULT_SOFTBOX: SoftboxSettings = {
  enabled: true,
  lightAngle: 45,
  lightElevation: 55,
  colorTempK: 5500,
  intensity: 100,
  softboxDiffusion: 65,
}

export const useEditorStore = create<EditorState>((set) => ({
  projectId: null,
  layers: MOCK_EDITOR_LAYERS,
  selectedLayerId: "layer_product",
  zoomMode: "fit",
  softbox: DEFAULT_SOFTBOX,
  productPreviewUrl: null,
  busyKind: "idle",
  setProjectId: (id) => set({ projectId: id }),
  selectLayer: (id) => set({ selectedLayerId: id }),
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
  setSoftbox: (patch) =>
    set((state) => ({ softbox: { ...state.softbox, ...patch } })),
  setProductPreviewUrl: (url) => set({ productPreviewUrl: url }),
  setBusyKind: (kind) => set({ busyKind: kind }),
  reset: () =>
    set({
      layers: MOCK_EDITOR_LAYERS,
      selectedLayerId: "layer_product",
      zoomMode: "fit",
      softbox: DEFAULT_SOFTBOX,
      productPreviewUrl: null,
      busyKind: "idle",
    }),
}))

export type { EditorBusyKind }
