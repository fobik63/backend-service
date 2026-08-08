export type CanvasLayerType = "image" | "text" | "shape" | "background"

export type EditorFontFamily =
  | "Inter"
  | "Montserrat"
  | "Roboto"
  | "Space Grotesk"

export type TextLayerStyle = {
  fontFamily: EditorFontFamily
  fontSize: number
  fontWeight: number
  color: string
  strokeWidth: number
  strokeColor: string
  shadowEnabled: boolean
  shadowColor: string
  shadowBlur: number
  shadowOffsetX: number
  shadowOffsetY: number
}

export type FeatureChipDraft = {
  label: string
  bgColor: string
  borderRadius: number
  iconId: string
}

export type CanvasLayer = {
  id: string
  type: CanvasLayerType
  name: string
  visible: boolean
  locked: boolean
  opacity: number
  zIndex: number
  /** Typography content — present on `type: "text"` layers. */
  text?: string
  textStyle?: TextLayerStyle
  /** Feature-chip extras — present on shape chips. */
  chip?: FeatureChipDraft
}

export type CanvasDocument = {
  id: string
  width: number
  height: number
  layers: CanvasLayer[]
  updatedAt: string
}

export const DEFAULT_TEXT_STYLE: TextLayerStyle = {
  fontFamily: "Inter",
  fontSize: 48,
  fontWeight: 700,
  color: "#FFFFFF",
  strokeWidth: 0,
  strokeColor: "#0F1115",
  shadowEnabled: true,
  shadowColor: "#00000066",
  shadowBlur: 6,
  shadowOffsetX: 0,
  shadowOffsetY: 2,
}

export const EDITOR_FONT_FAMILIES: EditorFontFamily[] = [
  "Inter",
  "Montserrat",
  "Roboto",
  "Space Grotesk",
]

export const FONT_WEIGHT_OPTIONS = [
  { value: 400, label: "Regular" },
  { value: 500, label: "Medium" },
  { value: 600, label: "SemiBold" },
  { value: 700, label: "Bold" },
  { value: 800, label: "ExtraBold" },
] as const
