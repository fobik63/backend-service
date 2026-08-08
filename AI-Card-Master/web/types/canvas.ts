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

export type FeatureChipVariant = "solid" | "glass"

export type FeatureChipDraft = {
  label: string
  bgColor: string
  borderRadius: number
  iconId: string
  /** `glass` = frosted translucent plate (backdrop-blur). */
  variant?: FeatureChipVariant
  /** Optional second line under the main label. */
  subtitle?: string
  /** Explicit text/icon color; falls back to contrast against bg. */
  textColor?: string
  /** Backdrop blur in px for glassmorphism (0 = none). */
  blur?: number
}

export type CanvasLayer = {
  id: string
  type: CanvasLayerType
  name: string
  visible: boolean
  locked: boolean
  opacity: number
  zIndex: number
  /** Top-left position on canvas as % of width/height (0–100). */
  x?: number
  y?: number
  /** Element size as % of canvas (image / product / text box). */
  width?: number
  height?: number
  /** Uniform scale multiplier (1 = 100%). */
  scale?: number
  /** Rotation in degrees (clockwise), around element center. */
  rotation?: number
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
