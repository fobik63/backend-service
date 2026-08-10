/** Shared canvas / API DTOs mirroring FastAPI schemas (snake_case wire format). */

export type LayerAlignment = "left" | "center" | "right"
export type BadgeType = "discount" | "rating" | "top_sales"
export type ShapeType = "rect" | "circle"
export type CanvasLayerTypeDTO = "image" | "text" | "badge" | "shape"

export type BaseLayerDTO = {
  id: string
  name: string
  visible?: boolean
  locked?: boolean
  x: number
  y: number
  width: number
  height: number
  /** Rotation in degrees (clockwise positive). */
  rotation?: number
  opacity?: number
  z_index?: number
}

export type ImageLayerDTO = BaseLayerDTO & {
  layer_type: "image"
  url: string
  scale_x?: number
  scale_y?: number
  crop_x?: number | null
  crop_y?: number | null
  crop_w?: number | null
  crop_h?: number | null
}

export type TextLayerDTO = BaseLayerDTO & {
  layer_type: "text"
  text: string
  font_family: string
  font_size: number
  font_weight: string
  color_hex: string
  alignment?: LayerAlignment
  line_height?: number
  letter_spacing?: number
  shadow_color?: string | null
  shadow_blur?: number
}

export type BadgeLayerDTO = BaseLayerDTO & {
  layer_type: "badge"
  badge_type: BadgeType
  text: string
  bg_color: string
  text_color: string
}

export type ShapeLayerDTO = BaseLayerDTO & {
  layer_type: "shape"
  shape_type: ShapeType
  fill_color: string
  stroke_color?: string | null
  stroke_width?: number
}

export type CanvasLayerDTO =
  | ImageLayerDTO
  | TextLayerDTO
  | BadgeLayerDTO
  | ShapeLayerDTO

/** Root canvas document sent to /canvas/render and returned by prompt-to-json. */
export type CanvasStateDTO = {
  width?: number
  height?: number
  background_color?: string
  background_image_url?: string | null
  layers?: CanvasLayerDTO[]
}

/** Parametric softbox — mirrors backend StudioLightDTO. */
export type StudioLightDTO = {
  light_angle?: number
  light_elevation?: number
  color_temp_k?: number
  intensity?: number
  softbox_diffusion?: number
}

export type EditorSoftboxDTO = {
  enabled: boolean
  light_angle: number
  light_elevation: number
  color_temp_k: number
  intensity: number
  softbox_diffusion: number
}

export type EditorTextStyleDTO = {
  font_family: "Inter" | "Montserrat" | "Roboto" | "Space Grotesk"
  font_size: number
  font_weight: number
  color: string
  stroke_width: number
  stroke_color: string
  shadow_enabled: boolean
  shadow_color: string
  shadow_blur: number
  shadow_offset_x: number
  shadow_offset_y: number
}

export type EditorChipDTO = {
  label: string
  subtitle?: string | null
  bg_color: string
  border_radius: number
  icon_id: string
  variant: "solid" | "glass"
  text_color?: string | null
  blur: number
}

export type EditorLayerBaseDTO = {
  id: string
  name: string
  visible: boolean
  locked: boolean
  opacity: number
  z_index: number
  x: number
  y: number
  width: number
  height: number
  scale: number
  rotation: number
}

export type EditorLayerDTO =
  | (EditorLayerBaseDTO & { type: "background" })
  | (EditorLayerBaseDTO & { type: "image" })
  | (EditorLayerBaseDTO & {
      type: "text"
      text: string
      text_style: EditorTextStyleDTO
    })
  | (EditorLayerBaseDTO & {
      type: "shape"
      chip: EditorChipDTO
    })

export type EditorDocumentDTO = {
  version: 1
  pages: Array<{
    id: string
    layers: EditorLayerDTO[]
  }>
  active_page_index: number
  pack_size: number
  product_preview_url?: string | null
  background_preview_url?: string | null
  softbox: EditorSoftboxDTO
}

export type SavedDesignDTO = {
  id: string
  title: string
  template_id?: string | null
  preview_url?: string | null
  canvas: CanvasStateDTO
  editor_document?: EditorDocumentDTO | null
  updated_at: string
}

export type SavedDesignListResponse = {
  items: SavedDesignDTO[]
  total: number
}

export type SaveDesignRequest = {
  id?: string | null
  title: string
  template_id?: string | null
  preview_url?: string | null
  canvas: CanvasStateDTO
  editor_document?: EditorDocumentDTO | null
}

/** POST /tools/remove-bg success payload. */
export type RemoveBgResponse = {
  success: boolean
  cdn_url: string
  object_key: string
  coins_charged: number
  new_balance: number
  width: number
  height: number
  content_type: string
  cost_coins: number
}

/** POST /generations → 202 Accepted. */
export type GenerationCreateResponse = {
  task_id: string
  status: string
  status_url: string
  idempotent_replay?: boolean
}

export type GenerationSlideStatus = {
  slide_key: string
  position: number
  status: string
  progress: number
  provider_used?: string | null
  result_url?: string | null
  warning?: string | null
  error?: { code: string; message: string; retryable: boolean } | null
}

/** GET /generations/{task_id} */
export type GenerationStatusResponse = {
  task_id: string
  status: string
  progress: number
  provider_used?: string | null
  warning?: string | null
  archive_url?: string | null
  slides: GenerationSlideStatus[]
  error?: { code: string; message: string; retryable: boolean } | null
  created_at: string
  updated_at: string
  completed_at?: string | null
}
