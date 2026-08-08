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

export const ICON_PRESETS = [
  { id: "icon_drop", label: "Капля" },
  { id: "icon_leaf", label: "Лист" },
  { id: "icon_shield", label: "Щит" },
  { id: "icon_star", label: "Звезда" },
  { id: "icon_spark", label: "Искра" },
  { id: "icon_box", label: "Коробка" },
  { id: "icon_flask", label: "Колба" },
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
