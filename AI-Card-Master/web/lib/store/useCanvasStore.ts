"use client"

import { create } from "zustand"

import { MOCK_EDITOR_LAYERS } from "@/lib/constants/mock-editor"
import type { SoftboxSettings } from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"
import { DEFAULT_TEXT_STYLE } from "@/types/canvas"

/** Virtual softbox knobs — same shape as editor SoftboxSettings. */
export type LightSettings = SoftboxSettings

export type CanvasPresetId = "default" | "sale" | "minimal" | "studio_soft" | "dramatic"

type CanvasSnapshot = {
  canvasState: CanvasLayer[]
  lightSettings: LightSettings
}

type HistoryStack = {
  past: CanvasSnapshot[]
  future: CanvasSnapshot[]
}

type CanvasStoreState = {
  /** Layers: text, product image, badges, prices. */
  canvasState: CanvasLayer[]
  /** Virtual softbox parameters. */
  lightSettings: LightSettings
  /** True while AI / canvas render is in flight. */
  isRendering: boolean
  /** Undo / redo stacks (snapshots of layers + light). */
  history: HistoryStack

  updateLayer: (id: string, patch: Partial<CanvasLayer>) => void
  setLightAngle: (angle: number) => void
  undo: () => void
  redo: () => void
  loadPreset: (presetId: CanvasPresetId) => void
  setIsRendering: (value: boolean) => void
}

const HISTORY_LIMIT = 50

const DEFAULT_LIGHT: LightSettings = {
  enabled: true,
  lightAngle: 45,
  lightElevation: 55,
  colorTempK: 5500,
  intensity: 100,
  softboxDiffusion: 65,
}

const PRICE_LAYER: CanvasLayer = {
  id: "layer_price",
  type: "text",
  name: "Цена",
  visible: true,
  locked: false,
  opacity: 1,
  zIndex: 5,
  text: "1 990 ₽",
  textStyle: {
    ...DEFAULT_TEXT_STYLE,
    fontSize: 56,
    color: "#F59E0B",
  },
}

function cloneLayers(layers: CanvasLayer[]): CanvasLayer[] {
  return layers.map((layer) => ({
    ...layer,
    textStyle: layer.textStyle ? { ...layer.textStyle } : undefined,
    chip: layer.chip ? { ...layer.chip } : undefined,
  }))
}

function cloneLight(light: LightSettings): LightSettings {
  return { ...light }
}

function snapshotOf(
  canvasState: CanvasLayer[],
  lightSettings: LightSettings
): CanvasSnapshot {
  return {
    canvasState: cloneLayers(canvasState),
    lightSettings: cloneLight(lightSettings),
  }
}

function pushPast(
  history: HistoryStack,
  snapshot: CanvasSnapshot
): HistoryStack {
  const past = [...history.past, snapshot]
  if (past.length > HISTORY_LIMIT) past.shift()
  return { past, future: [] }
}

function normalizeAngle(angle: number): number {
  const mod = angle % 360
  return mod < 0 ? mod + 360 : mod
}

function buildDefaultCanvasState(): CanvasLayer[] {
  return cloneLayers([...MOCK_EDITOR_LAYERS, PRICE_LAYER])
}

const SALE_LAYERS: CanvasLayer[] = [
  {
    id: "layer_bg",
    type: "background",
    name: "Фон",
    visible: true,
    locked: true,
    opacity: 1,
    zIndex: 0,
  },
  {
    id: "layer_product",
    type: "image",
    name: "Товар",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 1,
  },
  {
    id: "layer_title",
    type: "text",
    name: "Заголовок",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 2,
    text: "Скидка дня",
    textStyle: { ...DEFAULT_TEXT_STYLE, fontSize: 52 },
  },
  {
    id: "layer_badge",
    type: "shape",
    name: "Плашка «−30%»",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 3,
    x: 72,
    y: 6,
    chip: {
      label: "−30%",
      bgColor: "#E11D48",
      borderRadius: 8,
      iconId: "icon_spark",
    },
  },
  {
    id: "layer_price",
    type: "text",
    name: "Цена",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 4,
    text: "1 390 ₽",
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: 64,
      color: "#E11D48",
    },
  },
  {
    id: "layer_price_old",
    type: "text",
    name: "Старая цена",
    visible: true,
    locked: false,
    opacity: 0.75,
    zIndex: 5,
    text: "1 990 ₽",
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: 28,
      fontWeight: 500,
      color: "#A1A1AA",
    },
  },
]

const MINIMAL_LAYERS: CanvasLayer[] = [
  {
    id: "layer_bg",
    type: "background",
    name: "Фон",
    visible: true,
    locked: true,
    opacity: 1,
    zIndex: 0,
  },
  {
    id: "layer_product",
    type: "image",
    name: "Товар",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 1,
  },
  {
    id: "layer_title",
    type: "text",
    name: "Заголовок",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 2,
    text: "Название товара",
    textStyle: { ...DEFAULT_TEXT_STYLE, fontSize: 40, fontWeight: 600 },
  },
  {
    id: "layer_price",
    type: "text",
    name: "Цена",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 3,
    text: "2 490 ₽",
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: 44,
      color: "#FFFFFF",
    },
  },
]

/** Named canvas + softbox presets for `loadPreset`. */
export const CANVAS_PRESETS: Record<
  CanvasPresetId,
  { canvasState: CanvasLayer[]; lightSettings: LightSettings }
> = {
  default: {
    canvasState: buildDefaultCanvasState(),
    lightSettings: { ...DEFAULT_LIGHT },
  },
  sale: {
    canvasState: cloneLayers(SALE_LAYERS),
    lightSettings: {
      ...DEFAULT_LIGHT,
      lightAngle: 35,
      lightElevation: 50,
      colorTempK: 4800,
      intensity: 120,
      softboxDiffusion: 55,
    },
  },
  minimal: {
    canvasState: cloneLayers(MINIMAL_LAYERS),
    lightSettings: {
      ...DEFAULT_LIGHT,
      lightAngle: 90,
      lightElevation: 70,
      colorTempK: 5600,
      intensity: 90,
      softboxDiffusion: 80,
    },
  },
  studio_soft: {
    canvasState: buildDefaultCanvasState(),
    lightSettings: {
      enabled: true,
      lightAngle: 45,
      lightElevation: 60,
      colorTempK: 5500,
      intensity: 100,
      softboxDiffusion: 85,
    },
  },
  dramatic: {
    canvasState: buildDefaultCanvasState(),
    lightSettings: {
      enabled: true,
      lightAngle: 210,
      lightElevation: 25,
      colorTempK: 4200,
      intensity: 160,
      softboxDiffusion: 30,
    },
  },
}

const initialCanvas = buildDefaultCanvasState()

export const useCanvasStore = create<CanvasStoreState>((set, get) => ({
  canvasState: initialCanvas,
  lightSettings: cloneLight(DEFAULT_LIGHT),
  isRendering: false,
  history: { past: [], future: [] },

  updateLayer: (id, patch) => {
    const { canvasState, lightSettings, history } = get()
    const index = canvasState.findIndex((layer) => layer.id === id)
    if (index === -1) return

    const current = canvasState[index]!
    const nextLayer: CanvasLayer = {
      ...current,
      ...patch,
      textStyle:
        patch.textStyle !== undefined
          ? { ...current.textStyle, ...patch.textStyle }
          : current.textStyle,
      chip:
        patch.chip !== undefined
          ? { ...current.chip, ...patch.chip }
          : current.chip,
    }

    const nextState = canvasState.map((layer, i) =>
      i === index ? nextLayer : layer
    )

    set({
      canvasState: nextState,
      history: pushPast(history, snapshotOf(canvasState, lightSettings)),
    })
  },

  setLightAngle: (angle) => {
    const { canvasState, lightSettings, history } = get()
    const lightAngle = normalizeAngle(angle)
    if (lightSettings.lightAngle === lightAngle) return

    set({
      lightSettings: { ...lightSettings, lightAngle },
      history: pushPast(history, snapshotOf(canvasState, lightSettings)),
    })
  },

  undo: () => {
    const { canvasState, lightSettings, history } = get()
    const previous = history.past[history.past.length - 1]
    if (!previous) return

    set({
      canvasState: cloneLayers(previous.canvasState),
      lightSettings: cloneLight(previous.lightSettings),
      history: {
        past: history.past.slice(0, -1),
        future: [
          snapshotOf(canvasState, lightSettings),
          ...history.future,
        ].slice(0, HISTORY_LIMIT),
      },
    })
  },

  redo: () => {
    const { canvasState, lightSettings, history } = get()
    const next = history.future[0]
    if (!next) return

    set({
      canvasState: cloneLayers(next.canvasState),
      lightSettings: cloneLight(next.lightSettings),
      history: {
        past: [
          ...history.past,
          snapshotOf(canvasState, lightSettings),
        ].slice(-HISTORY_LIMIT),
        future: history.future.slice(1),
      },
    })
  },

  loadPreset: (presetId) => {
    const preset = CANVAS_PRESETS[presetId]
    if (!preset) return

    const { canvasState, lightSettings, history } = get()

    set({
      canvasState: cloneLayers(preset.canvasState),
      lightSettings: cloneLight(preset.lightSettings),
      history: pushPast(history, snapshotOf(canvasState, lightSettings)),
    })
  },

  setIsRendering: (value) => set({ isRendering: value }),
}))
