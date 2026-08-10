import type { CanvasLayer } from "@/types/canvas"
import {
  DEFAULT_ARTBOARD_HEIGHT,
  DEFAULT_ARTBOARD_WIDTH,
} from "@/lib/editor/format-presets"

/**
 * Live artboard pixel size — mutated via `syncCanvasDimensions` when the
 * marketplace format changes. ES module live bindings keep Fabric / export
 * readers in sync without rewriting every call site.
 */
export let CANVAS_WIDTH = DEFAULT_ARTBOARD_WIDTH
export let CANVAS_HEIGHT = DEFAULT_ARTBOARD_HEIGHT

export function syncCanvasDimensions(width: number, height: number): void {
  CANVAS_WIDTH = Math.max(1, Math.round(width))
  CANVAS_HEIGHT = Math.max(1, Math.round(height))
}

/** Isolated transparent product cutout used on the editor canvas. */
export const DEFAULT_PRODUCT_CUTOUT = "/projects/cream-sage-mist-product.png"

/**
 * Clean default stack: locked background + interactive product only.
 * Badges / texts are added consciously via the elements panel (BADGE_PRESETS / TEXT_PRESETS).
 */
export const MOCK_EDITOR_LAYERS: CanvasLayer[] = [
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
    x: 31.66,
    y: 11,
    // Pixel aspect matches cream-sage-mist-product.png (1134×2638)
    width: 36.68,
    height: 64,
    scale: 1,
    rotation: 0,
  },
]

export const FEATURE_CHIP_ICONS = [
  { id: "icon_check", label: "Галочка" },
  { id: "icon_drop", label: "Капля" },
  { id: "icon_leaf", label: "Лист" },
  { id: "icon_shield", label: "Щит" },
  { id: "icon_star", label: "Звезда" },
  { id: "icon_spark", label: "Искра" },
  { id: "icon_box", label: "Коробка" },
  { id: "icon_flask", label: "Колба" },
] as const

export const FEATURE_CHIP_BG_PRESETS = [
  "#FFFFFF",
  "#0F1115",
  "#059669",
  "#F59E0B",
  "#E11D48",
  "#1B3E2B",
] as const

export const TEXT_PRESETS = [
  { id: "txt_title", label: "Заголовок", sample: "Sage Mist" },
  {
    id: "txt_subtitle",
    label: "Подзаголовок",
    sample: "Крем для рук · 75 мл",
  },
  { id: "txt_bullet", label: "Пункт", sample: "• Состав / объём" },
] as const

export const BADGE_PRESETS = [
  {
    id: "badge_eco_formula",
    label: "Эко-формула",
    subtitle: "Натуральные ингредиенты",
    tone: "sage" as const,
    bgColor: "rgba(15,17,21,0.45)",
    iconId: "icon_leaf",
    variant: "glass" as const,
  },
  {
    id: "badge_hydrate",
    label: "Увлажнение 24ч",
    subtitle: "Интенсивное питание",
    tone: "sage" as const,
    bgColor: "rgba(15,17,21,0.45)",
    iconId: "icon_drop",
    variant: "glass" as const,
  },
  {
    id: "badge_paraben_free",
    label: "Без парабенов",
    subtitle: "Безопасный уход",
    tone: "sage" as const,
    bgColor: "rgba(15,17,21,0.45)",
    iconId: "icon_flask",
    variant: "glass" as const,
  },
  {
    id: "badge_hit",
    label: "Хит продаж",
    tone: "emerald" as const,
    bgColor: "#059669",
    iconId: "icon_star",
    variant: "solid" as const,
  },
  {
    id: "badge_sale",
    label: "−30%",
    tone: "amber" as const,
    bgColor: "#E11D48",
    iconId: "icon_spark",
    variant: "solid" as const,
  },
  {
    id: "badge_guarantee",
    label: "Гарантия",
    tone: "copper" as const,
    bgColor: "#F59E0B",
    iconId: "icon_shield",
    variant: "solid" as const,
  },
  {
    id: "badge_new",
    label: "Новинка",
    tone: "copper" as const,
    bgColor: "#B87333",
    iconId: "icon_spark",
    variant: "solid" as const,
  },
  {
    id: "badge_eco",
    label: "Eco",
    tone: "sage" as const,
    bgColor: "#1B3E2B",
    iconId: "icon_leaf",
    variant: "solid" as const,
  },
] as const

/** Default drop spot for the next badge/chip (% of canvas). */
export function nextBadgePosition(
  existingChipCount: number
): { x: number; y: number } {
  const col = existingChipCount % 2
  const row = Math.floor(existingChipCount / 2)
  return {
    x: 56 + col * 4,
    y: 24 + row * 12,
  }
}

function cloneLayers(layers: CanvasLayer[]): CanvasLayer[] {
  return layers.map((layer) => ({
    ...layer,
    textStyle: layer.textStyle ? { ...layer.textStyle } : undefined,
    chip: layer.chip ? { ...layer.chip } : undefined,
  }))
}

function bgLayer(page: number): CanvasLayer {
  return {
    id: `p${page}_bg`,
    type: "background",
    name: "Фон",
    visible: true,
    locked: true,
    opacity: 1,
    zIndex: 0,
  }
}

function productLayer(
  page: number,
  opts: { x: number; y: number; width: number; height: number; zIndex?: number }
): CanvasLayer {
  return {
    id: `p${page}_product`,
    type: "image",
    name: "Товар",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: opts.zIndex ?? 1,
    x: opts.x,
    y: opts.y,
    width: opts.width,
    height: opts.height,
    scale: 1,
    rotation: 0,
  }
}

/** Page 0 — main marketplace card (bg + product only). */
export function buildMainPageLayers(): CanvasLayer[] {
  return cloneLayers(
    MOCK_EDITOR_LAYERS.map((layer) => ({
      ...layer,
      id: layer.id.startsWith("layer_")
        ? `p0_${layer.id.slice("layer_".length)}`
        : `p0_${layer.id}`,
    }))
  )
}

/** Page 1 — features layout (clean: product higher for badge room). */
export function buildFeaturesPageLayers(): CanvasLayer[] {
  return [
    bgLayer(1),
    productLayer(1, { x: 21, y: 18, width: 58, height: 64 }),
  ]
}

/** Page 2 — benefits layout (clean centered product). */
export function buildBenefitsPageLayers(): CanvasLayer[] {
  return [
    bgLayer(2),
    productLayer(2, { x: 21, y: 18, width: 58, height: 64, zIndex: 1 }),
  ]
}

/** Page 3 — composition layout (clean centered product). */
export function buildCompositionPageLayers(): CanvasLayer[] {
  return [
    bgLayer(3),
    productLayer(3, { x: 21, y: 18, width: 58, height: 64, zIndex: 1 }),
  ]
}

/** Page 4 — CTA layout (clean centered product). */
export function buildCtaPageLayers(): CanvasLayer[] {
  return [
    bgLayer(4),
    productLayer(4, { x: 21, y: 18, width: 58, height: 64 }),
  ]
}

const PAGE_BUILDERS = [
  buildMainPageLayers,
  buildFeaturesPageLayers,
  buildBenefitsPageLayers,
  buildCompositionPageLayers,
  buildCtaPageLayers,
] as const

/** Build editable layer stacks for a card pack (pages 1…N) — bg + product only. */
export function buildDefaultPackPages(packSize: number): CanvasLayer[][] {
  const n = Math.max(1, Math.min(20, Math.floor(packSize) || 5))
  const pages: CanvasLayer[][] = []
  for (let i = 0; i < n; i += 1) {
    const builder = PAGE_BUILDERS[i % PAGE_BUILDERS.length]!
    const layers = builder()
    if (i < PAGE_BUILDERS.length) {
      pages.push(layers)
    } else {
      pages.push(
        layers.map((layer) => ({
          ...layer,
          id: `p${i}_${layer.id.replace(/^p\d+_/, "")}`,
        }))
      )
    }
  }
  return pages
}

export function defaultSelectedLayerId(layers: CanvasLayer[]): string | null {
  return (
    layers.find((l) => l.type === "image")?.id ??
    layers.find((l) => l.type !== "background")?.id ??
    null
  )
}
