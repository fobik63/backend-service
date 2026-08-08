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
  },
  {
    id: "layer_icon",
    type: "shape",
    name: "Иконка объёма",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 4,
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
  { id: "badge_hit", label: "Хит продаж", tone: "emerald" },
  { id: "badge_new", label: "Новинка", tone: "copper" },
  { id: "badge_sale", label: "−30%", tone: "amber" },
  { id: "badge_eco", label: "Eco", tone: "sage" },
] as const

export const ICON_PRESETS = [
  { id: "icon_drop", label: "Капля" },
  { id: "icon_leaf", label: "Лист" },
  { id: "icon_shield", label: "Щит" },
  { id: "icon_star", label: "Звезда" },
  { id: "icon_spark", label: "Искра" },
  { id: "icon_box", label: "Коробка" },
] as const
