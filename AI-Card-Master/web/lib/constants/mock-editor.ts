import type { CanvasLayer } from "@/types/canvas"
import { DEFAULT_TEXT_STYLE } from "@/types/canvas"

export const CANVAS_WIDTH = 1080
export const CANVAS_HEIGHT = 1440

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
    x: 27,
    y: 23,
    width: 46,
    height: 38,
    scale: 1,
    rotation: 0,
  },
  {
    id: "layer_title",
    type: "text",
    name: "Заголовок",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 2,
    x: 8,
    y: 68,
    width: 84,
    scale: 1,
    rotation: 0,
    text: "Название товара",
    textStyle: { ...DEFAULT_TEXT_STYLE },
  },
  {
    id: "layer_badge",
    type: "shape",
    name: "Плашка «Хит»",
    visible: true,
    locked: false,
    opacity: 0.95,
    zIndex: 3,
    x: 72,
    y: 6,
    scale: 1,
    rotation: 0,
    chip: {
      label: "Хит",
      bgColor: "#059669",
      borderRadius: 8,
      iconId: "icon_star",
    },
  },
  {
    id: "layer_icon",
    type: "shape",
    name: "Иконка объёма",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 4,
    x: 8,
    y: 86,
    scale: 1,
    rotation: 0,
    chip: {
      label: "Натуральный состав",
      bgColor: "#14171d",
      borderRadius: 10,
      iconId: "icon_check",
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
  { id: "txt_title", label: "Заголовок", sample: "Название товара" },
  { id: "txt_subtitle", label: "Подзаголовок", sample: "Ключевое преимущество" },
  { id: "txt_bullet", label: "Пункт", sample: "• Состав / объём" },
] as const

export const BADGE_PRESETS = [
  {
    id: "badge_hit",
    label: "Хит продаж",
    tone: "emerald" as const,
    bgColor: "#059669",
    iconId: "icon_star",
  },
  {
    id: "badge_sale",
    label: "−30%",
    tone: "amber" as const,
    bgColor: "#E11D48",
    iconId: "icon_spark",
  },
  {
    id: "badge_guarantee",
    label: "Гарантия",
    tone: "copper" as const,
    bgColor: "#F59E0B",
    iconId: "icon_shield",
  },
  {
    id: "badge_new",
    label: "Новинка",
    tone: "copper" as const,
    bgColor: "#B87333",
    iconId: "icon_spark",
  },
  {
    id: "badge_eco",
    label: "Eco",
    tone: "sage" as const,
    bgColor: "#1B3E2B",
    iconId: "icon_leaf",
  },
] as const

export const ICON_PRESETS = [
  { id: "icon_drop", label: "Капля" },
  { id: "icon_leaf", label: "Лист" },
  { id: "icon_shield", label: "Щит" },
  { id: "icon_star", label: "Звезда" },
  { id: "icon_spark", label: "Искра" },
  { id: "icon_box", label: "Коробка" },
] as const

/** Default drop spot for the next badge/chip (% of canvas). */
export function nextBadgePosition(
  existingChipCount: number
): { x: number; y: number } {
  const col = existingChipCount % 2
  const row = Math.floor(existingChipCount / 2)
  return {
    x: 58 + col * 14,
    y: 5 + row * 9,
  }
}
