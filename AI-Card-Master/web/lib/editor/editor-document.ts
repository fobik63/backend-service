import { z } from "zod"

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/lib/constants/mock-editor"
import type { SoftboxSettings } from "@/lib/store/editor-store"
import type {
  BadgeLayerDTO,
  CanvasLayerDTO,
  CanvasStateDTO,
  EditorDocumentDTO,
  EditorLayerDTO,
} from "@/types/api"
import {
  DEFAULT_TEXT_STYLE,
  type CanvasLayer,
  type TextLayerStyle,
} from "@/types/canvas"

const textStyleSchema = z
  .object({
    font_family: z.enum(["Inter", "Montserrat", "Roboto", "Space Grotesk"]),
    font_size: z.number().int().min(1).max(512),
    font_weight: z.number().int().min(100).max(900),
    color: z.string().min(1).max(64),
    stroke_width: z.number().min(0).max(32),
    stroke_color: z.string().min(1).max(64),
    shadow_enabled: z.boolean(),
    shadow_color: z.string().min(1).max(64),
    shadow_blur: z.number().min(0).max(128),
    shadow_offset_x: z.number().min(-256).max(256),
    shadow_offset_y: z.number().min(-256).max(256),
  })
  .strict()

const chipSchema = z
  .object({
    label: z.string().min(1).max(256),
    subtitle: z.string().max(256).nullish(),
    bg_color: z.string().min(1).max(128),
    border_radius: z.number().min(0).max(256),
    icon_id: z.string().min(1).max(128),
    variant: z.enum(["solid", "glass"]),
    text_color: z.string().min(1).max(64).nullish(),
    blur: z.number().min(0).max(128),
  })
  .strict()

const layerBaseShape = {
  id: z.string().min(1).max(256),
  name: z.string().min(1).max(256),
  visible: z.boolean(),
  locked: z.boolean(),
  opacity: z.number().min(0).max(1),
  z_index: z.number().int().min(-10_000).max(10_000),
  x: z.number().min(-200).max(300),
  y: z.number().min(-200).max(300),
  width: z.number().positive().max(500),
  height: z.number().positive().max(500),
  scale: z.number().positive().max(100),
  rotation: z.number().min(-3600).max(3600),
}

const editorLayerSchema = z.discriminatedUnion("type", [
  z.object({ ...layerBaseShape, type: z.literal("background") }).strict(),
  z.object({ ...layerBaseShape, type: z.literal("image") }).strict(),
  z
    .object({
      ...layerBaseShape,
      type: z.literal("text"),
      text: z.string().max(8000),
      text_style: textStyleSchema,
    })
    .strict(),
  z
    .object({
      ...layerBaseShape,
      type: z.literal("shape"),
      chip: chipSchema,
    })
    .strict(),
])

const softboxSchema = z
  .object({
    enabled: z.boolean(),
    light_angle: z.number().min(0).max(360),
    light_elevation: z.number().min(10).max(90),
    color_temp_k: z.number().int().min(2700).max(6500),
    intensity: z.number().min(0).max(200),
    softbox_diffusion: z.number().min(0).max(100),
  })
  .strict()

const editorDocumentSchema = z
  .object({
    version: z.literal(1),
    pages: z
      .array(
        z
          .object({
            id: z.string().min(1).max(128),
            layers: z.array(editorLayerSchema).min(1).max(256),
          })
          .strict()
      )
      .min(1)
      .max(20),
    active_page_index: z.number().int().min(0).max(19),
    pack_size: z.number().int().min(1).max(20),
    product_preview_url: z.string().min(1).max(2048).nullish(),
    softbox: softboxSchema,
  })
  .strict()
  .superRefine((document, context) => {
    if (document.pack_size !== document.pages.length) {
      context.addIssue({
        code: "custom",
        path: ["pack_size"],
        message: "pack_size must equal pages.length",
      })
    }
    if (document.active_page_index >= document.pages.length) {
      context.addIssue({
        code: "custom",
        path: ["active_page_index"],
        message: "active_page_index is outside pages",
      })
    }
    const pageIds = new Set(document.pages.map((page) => page.id))
    if (pageIds.size !== document.pages.length) {
      context.addIssue({
        code: "custom",
        path: ["pages"],
        message: "page ids must be unique",
      })
    }
  })

function layerDefaults(layer: CanvasLayer): EditorLayerDTO {
  return {
    id: layer.id,
    type: layer.type,
    name: layer.name,
    visible: layer.visible,
    locked: layer.locked,
    opacity: layer.opacity,
    z_index: layer.zIndex,
    x: layer.x ?? 0,
    y: layer.y ?? 0,
    width:
      layer.width ??
      (layer.type === "background" ? 100 : layer.type === "shape" ? 36 : 20),
    height:
      layer.height ??
      (layer.type === "background" ? 100 : layer.type === "shape" ? 9 : 12),
    scale: layer.scale ?? 1,
    rotation: layer.rotation ?? 0,
  } as EditorLayerDTO
}

function toEditorLayer(layer: CanvasLayer): EditorLayerDTO {
  const base = layerDefaults(layer)
  if (layer.type === "text") {
    const style = layer.textStyle ?? DEFAULT_TEXT_STYLE
    return {
      ...base,
      type: "text",
      text: layer.text ?? "",
      text_style: {
        font_family: style.fontFamily,
        font_size: style.fontSize,
        font_weight: style.fontWeight,
        color: style.color,
        stroke_width: style.strokeWidth,
        stroke_color: style.strokeColor,
        shadow_enabled: style.shadowEnabled,
        shadow_color: style.shadowColor,
        shadow_blur: style.shadowBlur,
        shadow_offset_x: style.shadowOffsetX,
        shadow_offset_y: style.shadowOffsetY,
      },
    }
  }
  if (layer.type === "shape") {
    const chip = layer.chip
    return {
      ...base,
      type: "shape",
      chip: {
        label: chip?.label.trim() || layer.name,
        subtitle: chip?.subtitle?.trim() || null,
        bg_color: chip?.bgColor || "#0F1115",
        border_radius: chip?.borderRadius ?? 14,
        icon_id: chip?.iconId || "icon_check",
        variant: chip?.variant ?? "solid",
        text_color: chip?.textColor ?? null,
        blur: chip?.blur ?? 0,
      },
    }
  }
  return base
}

function fromEditorLayer(layer: EditorLayerDTO): CanvasLayer {
  const base: CanvasLayer = {
    id: layer.id,
    type: layer.type,
    name: layer.name,
    visible: layer.visible,
    locked: layer.locked,
    opacity: layer.opacity,
    zIndex: layer.z_index,
    x: layer.x,
    y: layer.y,
    width: layer.width,
    height: layer.height,
    scale: layer.scale,
    rotation: layer.rotation,
  }
  if (layer.type === "text") {
    return {
      ...base,
      type: "text",
      text: layer.text,
      textStyle: {
        fontFamily: layer.text_style.font_family,
        fontSize: layer.text_style.font_size,
        fontWeight: layer.text_style.font_weight,
        color: layer.text_style.color,
        strokeWidth: layer.text_style.stroke_width,
        strokeColor: layer.text_style.stroke_color,
        shadowEnabled: layer.text_style.shadow_enabled,
        shadowColor: layer.text_style.shadow_color,
        shadowBlur: layer.text_style.shadow_blur,
        shadowOffsetX: layer.text_style.shadow_offset_x,
        shadowOffsetY: layer.text_style.shadow_offset_y,
      },
    }
  }
  if (layer.type === "shape") {
    return {
      ...base,
      type: "shape",
      chip: {
        label: layer.chip.label,
        subtitle: layer.chip.subtitle ?? undefined,
        bgColor: layer.chip.bg_color,
        borderRadius: layer.chip.border_radius,
        iconId: layer.chip.icon_id,
        variant: layer.chip.variant,
        textColor: layer.chip.text_color ?? undefined,
        blur: layer.chip.blur,
      },
    }
  }
  return base
}

function percentToPixels(value: number | undefined, dimension: number): number {
  return ((value ?? 0) / 100) * dimension
}

function validHex(value: string | undefined, fallback: string): string {
  return value && /^#(?:[\da-f]{3}|[\da-f]{6}|[\da-f]{8})$/i.test(value)
    ? value
    : fallback
}

function toCanvasLayerDTO(
  layer: CanvasLayer,
  productPreviewUrl: string | null
): CanvasLayerDTO | null {
  if (layer.type === "background") return null

  const base = {
    id: layer.id,
    name: layer.name,
    visible: layer.visible,
    locked: layer.locked,
    x: percentToPixels(layer.x, CANVAS_WIDTH),
    y: percentToPixels(layer.y, CANVAS_HEIGHT),
    width: Math.max(1, percentToPixels(layer.width ?? 10, CANVAS_WIDTH)),
    height: Math.max(1, percentToPixels(layer.height ?? 10, CANVAS_HEIGHT)),
    rotation: layer.rotation ?? 0,
    opacity: layer.opacity,
    z_index: layer.zIndex,
  }

  if (layer.type === "image") {
    if (!productPreviewUrl) return null
    return {
      ...base,
      layer_type: "image",
      url: productPreviewUrl,
      scale_x: layer.scale ?? 1,
      scale_y: layer.scale ?? 1,
    }
  }
  if (layer.type === "text") {
    const style: TextLayerStyle = layer.textStyle ?? DEFAULT_TEXT_STYLE
    return {
      ...base,
      layer_type: "text",
      text: layer.text ?? "",
      font_family: style.fontFamily,
      font_size: style.fontSize,
      font_weight: String(style.fontWeight),
      color_hex: validHex(style.color, "#FFFFFF"),
      alignment: "left",
      line_height: 1.2,
      letter_spacing: 0,
      shadow_color: style.shadowEnabled
        ? validHex(style.shadowColor, "#00000066")
        : null,
      shadow_blur: style.shadowEnabled ? style.shadowBlur : 0,
    }
  }

  const badge: BadgeLayerDTO = {
    ...base,
    layer_type: "badge",
    badge_type: "top_sales",
    text: layer.chip?.label.trim() || layer.name,
    bg_color: validHex(layer.chip?.bgColor, "#0F1115"),
    text_color: validHex(layer.chip?.textColor, "#FFFFFF"),
  }
  return badge
}

function pixelsToPercent(value: number, dimension: number): number {
  return (value / dimension) * 100
}

function fromCanvasLayerDTO(layer: CanvasLayerDTO): CanvasLayer {
  const base: CanvasLayer = {
    id: layer.id,
    type:
      layer.layer_type === "image"
        ? "image"
        : layer.layer_type === "text"
          ? "text"
          : "shape",
    name: layer.name,
    visible: layer.visible ?? true,
    locked: layer.locked ?? false,
    x: pixelsToPercent(layer.x, CANVAS_WIDTH),
    y: pixelsToPercent(layer.y, CANVAS_HEIGHT),
    width: pixelsToPercent(layer.width, CANVAS_WIDTH),
    height: pixelsToPercent(layer.height, CANVAS_HEIGHT),
    rotation: layer.rotation ?? 0,
    opacity: layer.opacity ?? 1,
    zIndex: layer.z_index ?? 0,
    scale:
      layer.layer_type === "image"
        ? Math.max(layer.scale_x ?? 1, layer.scale_y ?? 1)
        : 1,
  }
  if (layer.layer_type === "text") {
    return {
      ...base,
      type: "text",
      text: layer.text,
      textStyle: {
        ...DEFAULT_TEXT_STYLE,
        fontFamily:
          layer.font_family === "Montserrat" ||
          layer.font_family === "Roboto" ||
          layer.font_family === "Space Grotesk"
            ? layer.font_family
            : "Inter",
        fontSize: layer.font_size,
        fontWeight: Number(layer.font_weight) || 400,
        color: layer.color_hex,
        shadowEnabled: Boolean(layer.shadow_color),
        shadowColor: layer.shadow_color ?? DEFAULT_TEXT_STYLE.shadowColor,
        shadowBlur: layer.shadow_blur ?? 0,
      },
    }
  }
  if (layer.layer_type === "badge") {
    return {
      ...base,
      type: "shape",
      chip: {
        label: layer.text,
        bgColor: layer.bg_color,
        borderRadius: 14,
        iconId: "icon_check",
        variant: "solid",
        textColor: layer.text_color,
        blur: 0,
      },
    }
  }
  if (layer.layer_type === "shape") {
    return {
      ...base,
      type: "shape",
      chip: {
        label: layer.name,
        bgColor: layer.fill_color,
        borderRadius: layer.shape_type === "circle" ? 999 : 14,
        iconId: "icon_check",
        variant: "solid",
        textColor: "#FFFFFF",
        blur: 0,
      },
    }
  }
  return base
}

export function createEditorDocument(params: {
  pages: CanvasLayer[][]
  activePageIndex: number
  productPreviewUrl: string | null
  softbox: SoftboxSettings
}): EditorDocumentDTO {
  const document: EditorDocumentDTO = {
    version: 1,
    pages: params.pages.map((layers, index) => ({
      id: `page-${index + 1}`,
      layers: layers.map(toEditorLayer),
    })),
    active_page_index: params.activePageIndex,
    pack_size: params.pages.length,
    product_preview_url: params.productPreviewUrl,
    softbox: {
      enabled: params.softbox.enabled,
      light_angle: params.softbox.lightAngle,
      light_elevation: params.softbox.lightElevation,
      color_temp_k: params.softbox.colorTempK,
      intensity: params.softbox.intensity,
      softbox_diffusion: params.softbox.softboxDiffusion,
    },
  }
  return editorDocumentSchema.parse(document) as EditorDocumentDTO
}

export function parseEditorDocument(value: unknown): EditorDocumentDTO {
  return editorDocumentSchema.parse(value) as EditorDocumentDTO
}

export function editorDocumentToState(document: EditorDocumentDTO): {
  pages: CanvasLayer[][]
  activePageIndex: number
  productPreviewUrl: string | null
  softbox: SoftboxSettings
} {
  const parsed = parseEditorDocument(document)
  return {
    pages: parsed.pages.map((page) => page.layers.map(fromEditorLayer)),
    activePageIndex: parsed.active_page_index,
    productPreviewUrl: parsed.product_preview_url ?? null,
    softbox: {
      enabled: parsed.softbox.enabled,
      lightAngle: parsed.softbox.light_angle,
      lightElevation: parsed.softbox.light_elevation,
      colorTempK: parsed.softbox.color_temp_k,
      intensity: parsed.softbox.intensity,
      softboxDiffusion: parsed.softbox.softbox_diffusion,
    },
  }
}

export function layersToCanvasState(
  layers: CanvasLayer[],
  productPreviewUrl: string | null
): CanvasStateDTO {
  return {
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
    background_color: "#151719",
    background_image_url: null,
    layers: layers
      .map((layer) => toCanvasLayerDTO(layer, productPreviewUrl))
      .filter((layer): layer is CanvasLayerDTO => layer !== null),
  }
}

export function canvasStateToLayers(canvas: CanvasStateDTO): CanvasLayer[] {
  const background: CanvasLayer = {
    id: "layer_bg",
    type: "background",
    name: "Фон",
    visible: true,
    locked: true,
    opacity: 1,
    zIndex: 0,
    x: 0,
    y: 0,
    width: 100,
    height: 100,
    scale: 1,
    rotation: 0,
  }
  return [background, ...(canvas.layers ?? []).map(fromCanvasLayerDTO)]
}
