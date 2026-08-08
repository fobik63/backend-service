/** Shared canvas / API DTOs mirroring FastAPI schemas (snake_case wire format). */

export type LayerAlignment = "left" | "center" | "right"
export type BadgeType = "discount" | "rating" | "top_sales"
export type ShapeType = "rect" | "circle"
export type CanvasLayerTypeDTO = "image" | "text" | "badge" | "shape"
export type MarketplaceParserId = "wildberries" | "ozon"

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

/**
 * Client params for POST /relighting/custom.
 * Softbox knobs are flat (StudioLightDTO); wire body nests them under `studio_light`.
 */
export type RelightCustomParams = StudioLightDTO & {
  image_url: string
}

export type RelightProcessResponse = {
  success: boolean
  result_url: string
  object_key: string
  preset_name?: string | null
  studio_light?: StudioLightDTO | null
  coins_charged: number
  new_balance: number
  width: number
  height: number
  content_type: string
  cost_coins: number
}

export type ParsedProductCharacteristic = {
  name: string
  value: string
}

/** Ozon / Wildberries product payload from POST /parser/parse. */
export type ParsedProductDTO = {
  marketplace: MarketplaceParserId
  sku: string
  product_url: string
  title: string
  price_kopecks?: number | null
  price_before_discount_kopecks?: number | null
  currency?: string
  description?: string | null
  characteristics?: ParsedProductCharacteristic[]
  image_urls?: string[]
  total_stock?: number | null
}

/** Blob + object URL from canvas render (revoke objectUrl when done). */
export type RenderCanvasResult = {
  blob: Blob
  url: string
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
