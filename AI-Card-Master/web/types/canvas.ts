export type CanvasLayerType = "image" | "text" | "shape" | "background"

export type EditorFontFamily =
  | "Inter"
  | "Montserrat"
  | "Unbounded"
  | "Cera Pro"
  | "Oswald"
  | "Russo One"

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

/** Plate look — UI presets map 1:1 onto these variants. */
export type FeatureChipVariant = "solid" | "glass" | "dark" | "bordered"

export type FeatureChipDraft = {
  label: string
  bgColor: string
  borderRadius: number
  iconId: string
  /** Plate style preset variant. */
  variant?: FeatureChipVariant
  /** Optional second line under the main label. */
  subtitle?: string
  /** Explicit text/icon color; falls back to contrast against bg. */
  textColor?: string
  /** Backdrop blur in px for glassmorphism (0 = none). */
  blur?: number
  /** Plate outline color (glass rim / bordered). */
  strokeColor?: string
  /** Plate outline width in logical px. */
  strokeWidth?: number
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
  strokeColor: "#0d0f12",
  shadowEnabled: true,
  shadowColor: "#00000066",
  shadowBlur: 6,
  shadowOffsetX: 0,
  shadowOffsetY: 2,
}

export const EDITOR_FONT_FAMILIES: EditorFontFamily[] = [
  "Inter",
  "Montserrat",
  "Unbounded",
  "Cera Pro",
  "Oswald",
  "Russo One",
]

export const FONT_WEIGHT_OPTIONS = [
  { value: 400, label: "Regular" },
  { value: 500, label: "Medium" },
  { value: 600, label: "SemiBold" },
  { value: 700, label: "Bold" },
  { value: 800, label: "ExtraBold" },
] as const
