import {
  Ellipse,
  FabricImage,
  Shadow,
  type FabricObject,
} from "fabric"

import type { SoftboxSettings } from "@/lib/store/editor-store"

/** Coalesce slider → product shadow / filter paints (~1 frame @ 60fps). */
export const PRODUCT_LIGHTING_UPDATE_MS = 16

/** Cool shadow under warm key light (never pure black). */
export const SHADOW_TINT_COOL: [number, number, number] = [20, 25, 40]
/** Warm / neutral-brown shadow under cold key light. */
export const SHADOW_TINT_WARM: [number, number, number] = [35, 30, 25]
/** Dark tone mixed into auto-picked background shadow tint. */
const AUTO_TINT_DARK: [number, number, number] = [18, 16, 22]

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function clamp01(n: number) {
  return clamp(n, 0, 1)
}

function warmthFromKelvin(k: number) {
  return clamp01((6500 - k) / (6500 - 2700))
}

function mixRgb(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  const k = clamp01(t)
  return [
    Math.round(a[0] + (b[0] - a[0]) * k),
    Math.round(a[1] + (b[1] - a[1]) * k),
    Math.round(a[2] + (b[2] - a[2]) * k),
  ]
}

export type ProductCastParams = {
  /** Shadow fill RGB (alpha comes from the falloff bake). */
  rgb: [number, number, number]
  /** Opacity at the product base / contact line (0..1). */
  baseAlpha: number
  /** Opacity at the far tip of the cast (0..1). */
  tipAlpha: number
  /** Penumbra blur baked via ctx.filter (0–100px). */
  blur: number
  /**
   * Vertical flatten multiplier applied on top of the product scaleY.
   * Low sun (elevation → 0) → larger value (longer cast);
   * high sun (elevation → 90) → smaller value (short puddle).
   */
  flattenY: number
  /** Perspective shear in degrees (Fabric skewX). */
  skewX: number
  /** Secondary shear in degrees (Fabric skewY). */
  skewY: number
  /** Overall cast-layer opacity. */
  opacity: number
}

export type ProductContactParams = {
  color: string
  /** Ellipse half-width as fraction of product bounding width. */
  widthRatio: number
  /** Ellipse half-height as fraction of product bounding height. */
  heightRatio: number
  /** Vertical bias toward the bottom of the product (0..1 of height). */
  bottomBias: number
  opacity: number
  /** Contact / AO blur radius (2–6px). */
  blur: number
}

export type ProductShadowParams = {
  /** Perspective cast projection (separate canvas layer under the product). */
  cast: ProductCastParams
  /** Contact / ambient occlusion under the product base. */
  contact: ProductContactParams
}

export type ComputeProductShadowOptions = {
  /**
   * Darkest sampled background RGB for auto shadow tint.
   * Mixed with a dark tone so the result stays shadow-like.
   */
  backgroundTint?: [number, number, number] | null
}

/**
 * Complementary shadow tint from Kelvin, optionally overridden by auto bg sample.
 * Warm light → cool blue/violet shadow; cold light → warm brownish shadow.
 */
export function resolveShadowTintRgb(
  softbox: SoftboxSettings,
  backgroundTint?: [number, number, number] | null
): [number, number, number] {
  const warmth = warmthFromKelvin(softbox.colorTempK)
  // warmth 1 (2700K) → cool shadow; warmth 0 (6500K) → warm shadow.
  const fromTemp = mixRgb(SHADOW_TINT_COOL, SHADOW_TINT_WARM, 1 - warmth)

  if (!softbox.autoShadowTint || !backgroundTint) return fromTemp

  // Pull chroma from the darkest bg pixel, then crush toward a dark shadow tone.
  const fromBg = mixRgb(backgroundTint, AUTO_TINT_DARK, 0.55)
  return mixRgb(fromTemp, fromBg, 0.65)
}

/**
 * Derive dual-shadow params from softbox:
 * angle → skew / orbit around product base,
 * elevation → cast length (flattenY / scaleY),
 * shadowOpacity → both layers' opacity,
 * shadowBlur → cast ctx.filter blur (0–100px),
 * aoForce → contact AO strength,
 * Kelvin / auto tint → shadow RGB.
 */
export function computeProductShadowParams(
  softbox: SoftboxSettings,
  options: ComputeProductShadowOptions = {}
): ProductShadowParams | null {
  if (!softbox.enabled) return null

  const intensity = clamp(softbox.intensity / 100, 0, 2)
  const shadowOp = clamp01(softbox.shadowOpacity / 100)
  const aoForce = clamp01(softbox.aoForce / 100)
  const castBlur = clamp(softbox.shadowBlur, 0, 100)
  // 0° → long cast; 90° → short. Softbox UI clamps ~10–90; map full 0–90 range.
  const elevNorm = clamp01(softbox.lightElevation / 90)
  const rad = (softbox.lightAngle * Math.PI) / 180

  // Longer / less-flattened when the key light is low (scaleY projection).
  const flattenY = clamp(0.1 + (1 - elevNorm) * 0.62, 0.1, 0.75)
  // Stronger perspective shear at low elevation; direction opposite the key.
  // Orbit around product base as angle sweeps 0..360°.
  const skewAmt = 12 + (1 - elevNorm) * 36
  const skewX = -Math.cos(rad) * skewAmt
  const skewY = Math.sin(rad) * skewAmt * 0.2

  const shadowRgb = resolveShadowTintRgb(softbox, options.backgroundTint)

  const baseAlpha = clamp(0.55 + shadowOp * 0.35 + intensity * 0.05, 0.45, 0.95)
  const tipAlpha = clamp(0.02 + (1 - elevNorm) * 0.06, 0, 0.1)
  const castOpacity = clamp(shadowOp * (0.75 + intensity * 0.15), 0.05, 1)

  const contactAlpha = clamp(0.15 + aoForce * 0.7, 0.05, 0.9)
  const contactBlur = clamp(2 + aoForce * 4, 2, 6)
  const contactOpacity = clamp(0.25 + aoForce * 0.7, 0.1, 0.98)

  return {
    cast: {
      rgb: shadowRgb,
      baseAlpha,
      tipAlpha,
      blur: castBlur,
      flattenY,
      skewX,
      skewY,
      opacity: castOpacity,
    },
    contact: {
      color: `rgba(${shadowRgb[0]},${shadowRgb[1]},${shadowRgb[2]},${contactAlpha})`,
      widthRatio: 0.42 + (1 - elevNorm) * 0.08,
      heightRatio: 0.06 + aoForce * 0.05,
      bottomBias: 0.78,
      opacity: contactOpacity,
      blur: contactBlur,
    },
  }
}

/**
 * Sample the darkest opaque pixel from a background image source.
 * Returns null when the source is empty / fully transparent.
 */
export function sampleDarkestPixelRgb(
  source: CanvasImageSource,
  sampleSize = 48
): [number, number, number] | null {
  const size = Math.max(8, Math.min(96, Math.round(sampleSize)))
  const canvas = document.createElement("canvas")
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) return null

  try {
    ctx.drawImage(source, 0, 0, size, size)
  } catch {
    return null
  }

  let data: ImageData
  try {
    data = ctx.getImageData(0, 0, size, size)
  } catch {
    return null
  }

  let bestLum = Infinity
  let best: [number, number, number] | null = null
  const px = data.data
  for (let i = 0; i < px.length; i += 4) {
    const a = px[i + 3] ?? 0
    if (a < 32) continue
    const r = px[i] ?? 0
    const g = px[i + 1] ?? 0
    const b = px[i + 2] ?? 0
    // Perceptual luma — pick the darkest opaque sample.
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if (lum < bestLum) {
      bestLum = lum
      best = [r, g, b]
    }
  }
  return best
}

/** @deprecated Cast is a separate layer; kept for callers that still clear product.shadow. */
export function buildCastShadow(params: {
  color: string
  blur: number
  offsetX: number
  offsetY: number
}): Shadow {
  return new Shadow({
    color: params.color,
    blur: params.blur,
    offsetX: params.offsetX,
    offsetY: params.offsetY,
    affectStroke: false,
  })
}

export type ProductAoObject = Ellipse & {
  isProductAoShadow?: boolean
}

export type ProductCastObject = FabricImage & {
  isProductCastShadow?: boolean
  /** Cache key for the baked silhouette + falloff bitmap. */
  castBakeKey?: string
}

export function isProductAoShadow(obj: FabricObject): boolean {
  return Boolean((obj as ProductAoObject).isProductAoShadow)
}

export function isProductCastShadow(obj: FabricObject): boolean {
  return Boolean((obj as ProductCastObject).isProductCastShadow)
}

/** True for either companion shadow layer (cast or contact). */
export function isProductShadowCompanion(obj: FabricObject): boolean {
  return isProductAoShadow(obj) || isProductCastShadow(obj)
}

/** Non-interactive contact-shadow ellipse under the product. */
export function createProductAoShadow(): ProductAoObject {
  const ellipse = new Ellipse({
    originX: "center",
    originY: "center",
    rx: 40,
    ry: 10,
    fill: "rgba(20,25,40,0.55)",
    strokeWidth: 0,
    opacity: 0.7,
    selectable: false,
    evented: false,
    excludeFromExport: false,
    objectCaching: true,
    shadow: new Shadow({
      color: "rgba(20,25,40,0.45)",
      blur: 4,
      offsetX: 0,
      offsetY: 0,
    }),
  }) as ProductAoObject
  ellipse.isProductAoShadow = true
  return ellipse
}

/**
 * Bake a tinted alpha-mask silhouette with vertical falloff + ctx.filter blur.
 * Image bottom = product base (high opacity); top = cast tip (fades out).
 * Padding prevents blur clipping that would read as hard rectangular edges.
 */
export function bakeProductCastSilhouette(
  source: CanvasImageSource,
  width: number,
  height: number,
  cast: ProductCastParams
): HTMLCanvasElement {
  const w = Math.max(1, Math.round(width))
  const h = Math.max(1, Math.round(height))
  const blur = clamp(cast.blur, 0, 100)
  const pad = Math.ceil(blur * 2) + (blur > 0 ? 2 : 0)

  const raw = document.createElement("canvas")
  raw.width = w
  raw.height = h
  const rawCtx = raw.getContext("2d")
  if (!rawCtx) {
    const empty = document.createElement("canvas")
    empty.width = w
    empty.height = h
    return empty
  }

  rawCtx.clearRect(0, 0, w, h)
  rawCtx.drawImage(source, 0, 0, w, h)

  // Keep alpha, replace RGB with shadow color.
  rawCtx.globalCompositeOperation = "source-in"
  rawCtx.fillStyle = `rgb(${cast.rgb[0]},${cast.rgb[1]},${cast.rgb[2]})`
  rawCtx.fillRect(0, 0, w, h)

  // Falloff: opaque at base (bottom) → nearly transparent at tip (top).
  rawCtx.globalCompositeOperation = "destination-in"
  const grad = rawCtx.createLinearGradient(0, h, 0, 0)
  grad.addColorStop(0, `rgba(0,0,0,${clamp01(cast.baseAlpha)})`)
  grad.addColorStop(0.55, `rgba(0,0,0,${clamp01(cast.baseAlpha * 0.45)})`)
  grad.addColorStop(1, `rgba(0,0,0,${clamp01(cast.tipAlpha)})`)
  rawCtx.fillStyle = grad
  rawCtx.fillRect(0, 0, w, h)

  const outW = w + pad * 2
  const outH = h + pad * 2
  const canvas = document.createElement("canvas")
  canvas.width = outW
  canvas.height = outH
  const ctx = canvas.getContext("2d")
  if (!ctx) return raw

  ctx.clearRect(0, 0, outW, outH)
  if (blur > 0) {
    ctx.filter = `blur(${blur}px)`
  }
  ctx.drawImage(raw, pad, pad)
  ctx.filter = "none"

  return canvas
}

function castBakeKey(
  product: FabricImage,
  cast: ProductCastParams
): string {
  const el = product.getElement()
  const src =
    el instanceof HTMLImageElement
      ? el.src
      : el instanceof HTMLCanvasElement
        ? `canvas:${el.width}x${el.height}`
        : `el:${product.width}x${product.height}`
  return [
    src,
    Math.round(product.width ?? 0),
    Math.round(product.height ?? 0),
    cast.rgb.join(","),
    cast.baseAlpha.toFixed(3),
    cast.tipAlpha.toFixed(3),
    cast.blur.toFixed(1),
  ].join("|")
}

/** Empty placeholder cast layer (silhouette baked on first sync). */
export function createProductCastShadow(): ProductCastObject {
  const placeholder = document.createElement("canvas")
  placeholder.width = 1
  placeholder.height = 1
  const img = new FabricImage(placeholder, {
    originX: "center",
    originY: "bottom",
    left: 0,
    top: 0,
    selectable: false,
    evented: false,
    excludeFromExport: false,
    // Caching opaque bitmaps under multiply yields black rect artifacts on export.
    objectCaching: false,
    opacity: 0.8,
    globalCompositeOperation: "multiply",
  }) as ProductCastObject
  img.isProductCastShadow = true
  return img
}

/**
 * Rebake silhouette when the product bitmap or cast color/falloff/blur changes.
 * Transform-only gesture sync skips this (pass rebake: false).
 */
export function ensureProductCastBaked(
  castObj: ProductCastObject,
  product: FabricImage,
  cast: ProductCastParams
): void {
  const key = castBakeKey(product, cast)
  if (castObj.castBakeKey === key) return

  const el = product.getElement()
  if (!el) return

  const w = Math.max(1, product.width ?? 1)
  const h = Math.max(1, product.height ?? 1)
  const baked = bakeProductCastSilhouette(el, w, h, cast)
  castObj.setElement(baked, { width: baked.width, height: baked.height })
  castObj.castBakeKey = key
  castObj.set({ dirty: true })
}

/**
 * Position / size the AO ellipse from the product bounding box + softbox params.
 * Call on softbox change and while the product is dragged / rotated / scaled.
 */
export function syncProductAoShadow(
  ao: ProductAoObject,
  product: FabricObject,
  contact: ProductContactParams | null
): void {
  if (!contact) {
    ao.set({ visible: false, dirty: true })
    return
  }

  product.setCoords()
  const br = product.getBoundingRect()
  const cx = br.left + br.width / 2
  const cy = br.top + br.height * contact.bottomBias
  const rx = Math.max(4, (br.width * contact.widthRatio) / 2)
  const ry = Math.max(2, (br.height * contact.heightRatio) / 2)

  ao.set({
    visible: true,
    left: cx,
    top: cy,
    rx,
    ry,
    fill: contact.color,
    opacity: contact.opacity,
    shadow: new Shadow({
      color: contact.color,
      blur: contact.blur,
      offsetX: 0,
      offsetY: 0,
    }),
    dirty: true,
  })
  ao.setCoords()
}

/**
 * Anchor the cast projection to the product base and apply perspective flatten/skew.
 * Origin is bottom-center so the contact line stays glued while the silhouette
 * stretches away from the key light. Blur is baked into the bitmap (no Fabric Shadow).
 */
export function syncProductCastShadow(
  castObj: ProductCastObject,
  product: FabricObject,
  cast: ProductCastParams | null,
  options: { rebake?: boolean } = { rebake: true }
): void {
  if (!cast) {
    castObj.set({ visible: false, dirty: true })
    return
  }

  const rebake = options.rebake !== false
  if (rebake && (product instanceof FabricImage || product.type === "image")) {
    ensureProductCastBaked(castObj, product as FabricImage, cast)
  }

  product.setCoords()
  const base = product.getPointByOrigin("center", "bottom")

  // Compensate bake padding so the product base stays glued after blur pad.
  const blur = clamp(cast.blur, 0, 100)
  const pad = Math.ceil(blur * 2) + (blur > 0 ? 2 : 0)
  const sx = Math.abs(product.scaleX ?? 1)
  const sy = Math.abs(product.scaleY ?? 1) * cast.flattenY

  castObj.set({
    visible: true,
    left: base.x,
    top: base.y + pad * sy,
    originX: "center",
    originY: "bottom",
    scaleX: sx,
    scaleY: sy,
    angle: product.angle ?? 0,
    skewX: cast.skewX,
    skewY: cast.skewY,
    flipX: Boolean(product.flipX),
    flipY: Boolean(product.flipY),
    opacity: cast.opacity,
    globalCompositeOperation: "multiply",
    // Blur lives in the baked bitmap — Fabric Shadow would draw a black rect under multiply.
    shadow: null,
    objectCaching: false,
    dirty: true,
  })
  castObj.setCoords()
}

/**
 * Clear legacy fabric.Shadow on the product — cast lives on its own layer now.
 */
export function applyProductCastShadow(
  product: FabricImage | FabricObject,
  _params: ProductShadowParams | null
): void {
  product.set({ shadow: null, dirty: true })
}

/**
 * Prepare cast multiply layers for PNG export: opaque stage + no cache rects.
 * Call around canvas.toDataURL so multiply composites cleanly without black squares.
 */
export async function withMultiplySafeCastExport<T>(
  objects: FabricObject[],
  run: () => T | Promise<T>
): Promise<T> {
  const casts = objects.filter(isProductCastShadow) as ProductCastObject[]
  const restore = casts.map((obj) => ({
    obj,
    gco: obj.globalCompositeOperation,
    caching: obj.objectCaching,
    shadow: obj.shadow,
  }))

  for (const { obj } of restore) {
    obj.set({
      globalCompositeOperation: "multiply",
      objectCaching: false,
      shadow: null,
      dirty: true,
    })
  }

  try {
    return await run()
  } finally {
    for (const prev of restore) {
      prev.obj.set({
        globalCompositeOperation: prev.gco,
        objectCaching: prev.caching,
        shadow: prev.shadow,
        dirty: true,
      })
    }
  }
}
