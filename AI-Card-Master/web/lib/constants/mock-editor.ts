import type { CanvasLayer } from "@/types/canvas"
import { DEFAULT_TEXT_STYLE } from "@/types/canvas"

export const CANVAS_WIDTH = 1080
export const CANVAS_HEIGHT = 1440

/** Isolated transparent product cutout used on the editor canvas. */
export const DEFAULT_PRODUCT_CUTOUT = "/projects/cream-sage-mist-product.png"

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
  {
    id: "layer_title",
    type: "text",
    name: "Название",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 2,
    x: 8,
    y: 74,
    width: 70,
    scale: 1,
    rotation: 0,
    text: "Sage Mist",
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: 56,
      fontWeight: 700,
    },
  },
  {
    id: "layer_subtitle",
    type: "text",
    name: "Подзаголовок",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 3,
    x: 8,
    y: 82,
    width: 70,
    scale: 1,
    rotation: 0,
    text: "Крем для рук · 75 мл",
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: 26,
      fontWeight: 500,
      color: "#D4A574",
      shadowEnabled: false,
    },
  },
  {
    id: "layer_badge_eco",
    type: "shape",
    name: "Плашка «Эко-формула»",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 4,
    x: 56,
    y: 26,
    scale: 1,
    rotation: 0,
    chip: {
      label: "Эко-формула",
      subtitle: "Натуральные ингредиенты",
      bgColor: "rgba(15,17,21,0.45)",
      borderRadius: 14,
      iconId: "icon_leaf",
      variant: "glass",
      textColor: "#FFFFFF",
      blur: 12,
    },
  },
  {
    id: "layer_badge_hydrate",
    type: "shape",
    name: "Плашка «Увлажнение 24ч»",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 5,
    x: 56,
    y: 38,
    scale: 1,
    rotation: 0,
    chip: {
      label: "Увлажнение 24ч",
      subtitle: "Интенсивное питание",
      bgColor: "rgba(15,17,21,0.45)",
      borderRadius: 14,
      iconId: "icon_drop",
      variant: "glass",
      textColor: "#FFFFFF",
      blur: 12,
    },
  },
  {
    id: "layer_badge_paraben",
    type: "shape",
    name: "Плашка «Без парабенов»",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 6,
    x: 56,
    y: 50,
    scale: 1,
    rotation: 0,
    chip: {
      label: "Без парабенов",
      subtitle: "Безопасный уход",
      bgColor: "rgba(15,17,21,0.45)",
      borderRadius: 14,
      iconId: "icon_flask",
      variant: "glass",
      textColor: "#FFFFFF",
      blur: 12,
    },
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

function textLayer(
  page: number,
  id: string,
  opts: {
    name: string
    text: string
    x: number
    y: number
    width?: number
    zIndex: number
    fontSize: number
    fontWeight?: number
    color?: string
    shadowEnabled?: boolean
  }
): CanvasLayer {
  return {
    id: `p${page}_${id}`,
    type: "text",
    name: opts.name,
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: opts.zIndex,
    x: opts.x,
    y: opts.y,
    width: opts.width ?? 84,
    scale: 1,
    rotation: 0,
    text: opts.text,
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      fontSize: opts.fontSize,
      fontWeight: opts.fontWeight ?? 700,
      color: opts.color ?? "#FFFFFF",
      shadowEnabled: opts.shadowEnabled ?? true,
    },
  }
}

function badgeLayer(
  page: number,
  id: string,
  opts: {
    name: string
    x: number
    y: number
    zIndex: number
    label: string
    subtitle?: string
    iconId: string
    bgColor?: string
    variant?: "glass" | "solid"
  }
): CanvasLayer {
  return {
    id: `p${page}_${id}`,
    type: "shape",
    name: opts.name,
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: opts.zIndex,
    x: opts.x,
    y: opts.y,
    scale: 1,
    rotation: 0,
    chip: {
      label: opts.label,
      subtitle: opts.subtitle,
      bgColor: opts.bgColor ?? "rgba(15,17,21,0.45)",
      borderRadius: 14,
      iconId: opts.iconId,
      variant: opts.variant ?? "glass",
      textColor: "#FFFFFF",
      blur: opts.variant === "solid" ? 0 : 12,
    },
  }
}

/** Page 0 — main marketplace card (editable mock). */
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

/** Page 1 — features / advantages. */
export function buildFeaturesPageLayers(): CanvasLayer[] {
  return [
    bgLayer(1),
    productLayer(1, { x: 21, y: 6, width: 58, height: 36 }),
    textLayer(1, "eyebrow", {
      name: "Рубрика",
      text: "Инфографика · 02",
      x: 8,
      y: 46,
      zIndex: 2,
      fontSize: 22,
      fontWeight: 600,
      color: "#C2A68C",
      shadowEnabled: false,
    }),
    textLayer(1, "title", {
      name: "Заголовок",
      text: "Sage Mist",
      x: 8,
      y: 52,
      zIndex: 3,
      fontSize: 52,
    }),
    badgeLayer(1, "badge_a", {
      name: "Плашка «Эко-формула»",
      x: 8,
      y: 66,
      zIndex: 4,
      label: "Эко-формула",
      subtitle: "Натуральные ингредиенты",
      iconId: "icon_leaf",
      bgColor: "#059669",
      variant: "solid",
    }),
    badgeLayer(1, "badge_b", {
      name: "Плашка «Увлажнение 24ч»",
      x: 52,
      y: 66,
      zIndex: 5,
      label: "Увлажнение 24ч",
      subtitle: "Интенсивное питание",
      iconId: "icon_drop",
    }),
    badgeLayer(1, "badge_c", {
      name: "Плашка «Без парабенов»",
      x: 8,
      y: 78,
      zIndex: 6,
      label: "Без парабенов",
      subtitle: "Безопасный уход",
      iconId: "icon_flask",
      bgColor: "#059669",
      variant: "solid",
    }),
    badgeLayer(1, "badge_d", {
      name: "Плашка «Хит продаж»",
      x: 52,
      y: 78,
      zIndex: 7,
      label: "Хит продаж",
      iconId: "icon_star",
    }),
  ]
}

/** Page 2 — benefits / why choose. */
export function buildBenefitsPageLayers(): CanvasLayer[] {
  return [
    bgLayer(2),
    textLayer(2, "eyebrow", {
      name: "Рубрика",
      text: "Инфографика · 03",
      x: 8,
      y: 6,
      zIndex: 2,
      fontSize: 22,
      fontWeight: 600,
      color: "#C2A68C",
      shadowEnabled: false,
    }),
    textLayer(2, "title", {
      name: "Заголовок",
      text: "Почему выбирают",
      x: 8,
      y: 12,
      zIndex: 3,
      fontSize: 48,
    }),
    productLayer(2, { x: 21, y: 22, width: 58, height: 34, zIndex: 1 }),
    badgeLayer(2, "badge_a", {
      name: "Плашка «Эко-формула»",
      x: 8,
      y: 62,
      zIndex: 4,
      label: "✓ Эко-формула",
      iconId: "icon_check",
      bgColor: "#059669",
      variant: "solid",
    }),
    badgeLayer(2, "badge_b", {
      name: "Плашка «Увлажнение»",
      x: 8,
      y: 74,
      zIndex: 5,
      label: "✓ Увлажнение 24ч",
      iconId: "icon_check",
    }),
    badgeLayer(2, "badge_c", {
      name: "Плашка «Без парабенов»",
      x: 8,
      y: 86,
      zIndex: 6,
      label: "✓ Без парабенов",
      iconId: "icon_check",
      bgColor: "#059669",
      variant: "solid",
    }),
  ]
}

/** Page 3 — composition grid. */
export function buildCompositionPageLayers(): CanvasLayer[] {
  return [
    bgLayer(3),
    textLayer(3, "eyebrow", {
      name: "Рубрика",
      text: "Инфографика · 04",
      x: 8,
      y: 6,
      zIndex: 2,
      fontSize: 22,
      fontWeight: 600,
      color: "#C2A68C",
      shadowEnabled: false,
    }),
    textLayer(3, "title", {
      name: "Заголовок",
      text: "Состав и свойства",
      x: 8,
      y: 12,
      zIndex: 3,
      fontSize: 48,
    }),
    badgeLayer(3, "cell_a", {
      name: "Плашка «Натуральные»",
      x: 8,
      y: 28,
      zIndex: 4,
      label: "Натуральные компоненты",
      iconId: "icon_leaf",
    }),
    badgeLayer(3, "cell_b", {
      name: "Плашка «Без парабенов»",
      x: 52,
      y: 28,
      zIndex: 5,
      label: "Без парабенов",
      iconId: "icon_flask",
      bgColor: "#059669",
      variant: "solid",
    }),
    badgeLayer(3, "cell_c", {
      name: "Плашка «Клинически»",
      x: 8,
      y: 48,
      zIndex: 6,
      label: "Клинически проверено",
      iconId: "icon_shield",
      bgColor: "#059669",
      variant: "solid",
    }),
    badgeLayer(3, "cell_d", {
      name: "Плашка «Ежедневно»",
      x: 52,
      y: 48,
      zIndex: 7,
      label: "Подходит ежедневно",
      iconId: "icon_star",
    }),
    productLayer(3, { x: 36, y: 72, width: 28, height: 18, zIndex: 1 }),
  ]
}

/** Page 4 — CTA / details. */
export function buildCtaPageLayers(): CanvasLayer[] {
  return [
    bgLayer(4),
    productLayer(4, { x: 21, y: 8, width: 58, height: 46 }),
    textLayer(4, "eyebrow", {
      name: "Рубрика",
      text: "Инфографика · 05",
      x: 8,
      y: 58,
      zIndex: 2,
      fontSize: 22,
      fontWeight: 600,
      color: "#C2A68C",
      shadowEnabled: false,
    }),
    textLayer(4, "title", {
      name: "Заголовок",
      text: "Sage Mist",
      x: 8,
      y: 64,
      zIndex: 3,
      fontSize: 48,
    }),
    badgeLayer(4, "cta", {
      name: "Плашка CTA",
      x: 8,
      y: 78,
      zIndex: 4,
      label: "Готово к публикации на Ozon / WB",
      iconId: "icon_spark",
      bgColor: "#059669",
      variant: "solid",
    }),
  ]
}

const PAGE_BUILDERS = [
  buildMainPageLayers,
  buildFeaturesPageLayers,
  buildBenefitsPageLayers,
  buildCompositionPageLayers,
  buildCtaPageLayers,
] as const

/** Build editable layer stacks for a card pack (pages 1…N). */
export function buildDefaultPackPages(packSize: number): CanvasLayer[][] {
  const n = Math.max(1, Math.min(20, Math.floor(packSize) || 5))
  const pages: CanvasLayer[][] = []
  for (let i = 0; i < n; i += 1) {
    const builder = PAGE_BUILDERS[i % PAGE_BUILDERS.length]!
    const layers = builder()
    if (i < PAGE_BUILDERS.length) {
      pages.push(layers)
    } else {
      const cycle = Math.floor(i / PAGE_BUILDERS.length) + 1
      pages.push(
        layers.map((layer) => ({
          ...layer,
          id: `p${i}_${layer.id.replace(/^p\d+_/, "")}`,
          text:
            layer.type === "text" && layer.id.includes("title") && layer.text
              ? `${layer.text} ${cycle}`
              : layer.text,
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
