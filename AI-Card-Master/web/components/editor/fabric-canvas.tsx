"use client"

import {
  Canvas as FabricCanvas,
  FabricImage,
  FabricObject,
  BaseFabricObject,
  Group,
  InteractiveFabricObject,
  IText,
  Line,
  Rect,
  Shadow,
  Textbox,
  config as fabricConfig,
  initFilterBackend,
  type FabricObjectProps,
} from "fabric"
import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react"

import { GenerationBusyOverlay } from "@/components/editor/generation-busy-overlay"
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { resetLayerToDefaults, recoverCanvasAfterRenderError } from "@/lib/editor/canvas-error-recovery"
import {
  FABRIC_EXPORT_PRESETS,
  fabricCanvasToPngBytes,
  fabricCanvasToPngDataUrl,
  registerFabricExporter,
  type FabricExportSize,
} from "@/lib/editor/fabric-export"
import { resolveFabricFontFamily } from "@/lib/editor/fabric-fonts"
import { chipIconDataUrl, chipTextColor } from "@/lib/editor/fabric-icons"
import {
  applyChipLiveColors,
  isChipAppearanceScrubbing,
  rememberChipIconFg,
} from "@/lib/editor/chip-live"
import {
  applyFabricZoomView,
  computeFitZoom,
  FABRIC_FIT_PADDING,
  resolveFitContainerSize,
  type FabricViewportFrame,
} from "@/lib/editor/fabric-viewport"
import {
  boundsFromRect,
  canvasBounds,
  snapMoveToTargets,
  type SmartGuideLine,
} from "@/lib/editor/smart-guides"
import {
  createSoftboxSourceCanvas,
  paintSoftboxInPlace,
  SOFTBOX_UPDATE_MS,
  softboxLightBlendStyle,
  softboxOverlayStyle,
  clearSoftboxCaches,
} from "@/lib/editor/softbox"
import {
  useEditorStore,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import type {
  CanvasLayer,
  FeatureChipDraft,
  TextLayerStyle,
} from "@/types/canvas"
import { DEFAULT_TEXT_STYLE } from "@/types/canvas"
import { cn } from "@/lib/utils"

type LayerRole = "background" | "product" | "infographic"
type ChipPart = "bg" | "icon" | "label" | "subtitle"

type EngineObject = FabricObject & {
  layerId?: string
  layerRole?: LayerRole
  isSmartGuide?: boolean
  isSoftbox?: boolean
  /** Marks a child inside a chip Group (label is the editable part). */
  chipPart?: ChipPart
  /** Temporary top-level IText used while editing a chip label. */
  isChipInlineEditor?: boolean
  /**
   * Chip groups are authored at CHIP_SOURCE_SCALE× then scaled down.
   * Layer `scale` is logical; Fabric scaleX/Y = layer.scale / chipSourceScale.
   */
  chipSourceScale?: number
  /** Canvas left/top snapped before nested chip text edit / layout. */
  __badgeAbsLeft?: number
  __badgeAbsTop?: number
  /** Last in-bounds scale during an object:scaling gesture. */
  lastGoodScaleX?: number
  lastGoodScaleY?: number
  /** Last in-bounds position paired with lastGoodScale (corner handles move left/top). */
  lastGoodLeft?: number
  lastGoodTop?: number
}

/** Author chip geometry at 3×; place on canvas via scaleX/Y so vectors stay sharp when shrunk. */
const CHIP_SOURCE_SCALE = 3
/** Visual margin before the canvas right edge (logical canvas px). */
const CHIP_CANVAS_EDGE_MARGIN = 24

/**
 * Max Textbox width in chip source coords: grow with typing until the plate
 * would hit the canvas right edge (or a sane floor for off-canvas groups).
 */
function chipTextWidthBarrier(args: {
  hi: number
  padX: number
  iconSize: number
  gap: number
  groupLeft: number
  groupScaleX: number
}): number {
  const chrome = args.padX * 2 + args.iconSize + args.gap
  const groupScale = Math.max(0.01, args.groupScaleX)
  const maxPlateVisual = Math.max(
    160,
    CANVAS_WIDTH - args.groupLeft - CHIP_CANVAS_EDGE_MARGIN
  )
  const maxPlateSource = maxPlateVisual / groupScale
  // Keep enough room for a few glyphs even if the badge sits near the right edge.
  return Math.max(120 * args.hi, maxPlateSource - chrome)
}

/**
 * Fit Textbox to content width, wrap only after the barrier.
 * Uses word wrap by default; grapheme split only when a run exceeds the barrier
 * (otherwise Fabric wraps the last letter onto a second line — orphan glyph bug).
 */
function fitChipTextboxWidth(text: Textbox, maxTextWidth: number): number {
  const minW = Math.max(20, text.minWidth || 20)
  const raw = text.text ?? ""
  const hasExplicitNewline = /\r?\n/.test(raw)
  // Safety pad: width === calcTextWidth() makes Fabric wrap the last glyph.
  const pad = Math.max(4, Math.ceil((text.fontSize || 16) * 0.12))

  // Measure natural width without wrapping.
  text.set({ width: Math.max(maxTextWidth, 1e5), splitByGrapheme: false })
  if (typeof text.initDimensions === "function") text.initDimensions()
  const natural = Math.ceil(text.calcTextWidth() || minW)

  // Character wrap only when content cannot fit the canvas barrier in one run.
  const needsGraphemeSplit = natural > maxTextWidth
  let nextW = Math.min(Math.max(natural + pad, minW), maxTextWidth)

  text.set({
    width: nextW,
    splitByGrapheme: needsGraphemeSplit,
  })
  ;(text as Textbox & { breakWords?: boolean }).breakWords = true
  if (typeof text.initDimensions === "function") text.initDimensions()

  // Kill phantom orphan wraps on single-line labels (width still slightly short).
  if (!hasExplicitNewline && !needsGraphemeSplit) {
    let guard = 0
    while (
      (text.textLines?.length ?? 1) > 1 &&
      nextW < maxTextWidth &&
      guard < 12
    ) {
      nextW = Math.min(nextW + pad, maxTextWidth)
      text.set({ width: nextW, splitByGrapheme: false })
      if (typeof text.initDimensions === "function") text.initDimensions()
      guard += 1
    }
  }

  return nextW
}

function isChipTextObjectType(type: string | undefined): boolean {
  return type === "textbox" || type === "i-text"
}

const GUIDE_STROKE = "rgba(94, 184, 255, 0.92)"
const GUIDE_STROKE_WIDTH = 1

/**
 * Fabric v6: enableGLFiltering ≈ classic `EnableWebGL`.
 * Cap textureSize at 2048 to avoid OOM on weaker GPUs while accelerating filters.
 */
let fabricWebGlReady = false
function ensureFabricWebGL(): void {
  if (fabricWebGlReady || typeof window === "undefined") return
  fabricWebGlReady = true
  try {
    fabricConfig.configure({
      enableGLFiltering: true,
      textureSize: 2048,
    })
    initFilterBackend()
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn("[fabric-canvas] WebGL filter backend unavailable", err)
    }
  }
}

/**
 * Retina + sharp transforms: disable object bitmap caches that go soft when
 * badges/icons are scaled down. Fabric's prop is `noScaleCache` (not noScaleReset);
 * false = regenerate during scale so cache never stays at a low-res snapshot.
 */
let fabricQualityDefaultsReady = false
function ensureFabricQualityDefaults(): void {
  if (fabricQualityDefaultsReady) return
  fabricQualityDefaultsReady = true
  // v6 splits defaults: caching on BaseFabricObject, noScaleCache on interactive.
  BaseFabricObject.ownDefaults.objectCaching = false
  InteractiveFabricObject.ownDefaults.noScaleCache = false
  FabricObject.prototype.objectCaching = false
  FabricObject.prototype.noScaleCache = false
}

function ensureCustomProps(): void {
  const keys = [
    "layerId",
    "layerRole",
    "isSmartGuide",
    "isSoftbox",
    "chipPart",
    "isChipInlineEditor",
    "chipSourceScale",
  ]
  const existing = FabricObject.customProperties ?? []
  FabricObject.customProperties = Array.from(new Set([...existing, ...keys]))
}

function isSmartGuideObject(obj: FabricObject): boolean {
  return Boolean((obj as EngineObject).isSmartGuide)
}

function clearSmartGuides(canvas: FabricCanvas): void {
  const guides = canvas.getObjects().filter(isSmartGuideObject)
  if (guides.length === 0) return
  for (const g of guides) canvas.remove(g)
}

function guideSignature(guides: SmartGuideLine[]): string {
  return guides
    .map((g) => `${g.orientation[0]}:${Math.round(g.position)}`)
    .sort()
    .join("|")
}

function paintSmartGuides(
  canvas: FabricCanvas,
  guides: SmartGuideLine[],
  lastSigRef: { current: string }
): void {
  const nextSig = guideSignature(guides)
  if (nextSig === lastSigRef.current) return
  lastSigRef.current = nextSig

  clearSmartGuides(canvas)
  if (guides.length === 0) {
    canvas.requestRenderAll()
    return
  }

  const prevRender = canvas.renderOnAddRemove
  canvas.renderOnAddRemove = false
  for (const guide of guides) {
    const line =
      guide.orientation === "vertical"
        ? new Line([guide.position, 0, guide.position, CANVAS_HEIGHT], {
            stroke: GUIDE_STROKE,
            strokeWidth: GUIDE_STROKE_WIDTH,
            selectable: false,
            evented: false,
            excludeFromExport: true,
            hoverCursor: "default",
            strokeDashArray: [6, 4],
            objectCaching: false,
          })
        : new Line([0, guide.position, CANVAS_WIDTH, guide.position], {
            stroke: GUIDE_STROKE,
            strokeWidth: GUIDE_STROKE_WIDTH,
            selectable: false,
            evented: false,
            excludeFromExport: true,
            hoverCursor: "default",
            strokeDashArray: [6, 4],
            objectCaching: false,
          })
    ;(line as EngineObject).isSmartGuide = true
    canvas.add(line)
  }
  canvas.renderOnAddRemove = prevRender
  canvas.requestRenderAll()
}

function collectSnapTargets(
  canvas: FabricCanvas,
  moving: EngineObject
): ReturnType<typeof boundsFromRect>[] {
  const targets = [canvasBounds(CANVAS_WIDTH, CANVAS_HEIGHT)]
  for (const obj of canvas.getObjects()) {
    const engine = obj as EngineObject
    if (engine === moving) continue
    if (isSmartGuideObject(obj)) continue
    if (engine.layerRole === "background") continue
    if (!engine.layerId) continue
    const bound = obj.getBoundingRect()
    const box = boundsFromRect(bound)
    if (engine.layerRole === "product") {
      targets.splice(1, 0, box)
    } else {
      targets.push(box)
    }
  }
  return targets
}

/**
 * Keep a dragged object's axis-aligned bounding box inside the artboard.
 * Only adjusts left/top — never scale/angle — so rotate & scale stay intact.
 * Uses artboard size (CANVAS_*), not the zoomed viewport (canvas.width/height).
 */
function constrainObjectToArtboard(obj: FabricObject): void {
  const engine = obj as EngineObject
  if (isSmartGuideObject(obj)) return
  if (engine.layerRole === "background") return
  if (engine.isSoftbox || engine.isChipInlineEditor) return

  // Refresh aCoords so getBoundingRect matches the current drag position.
  obj.setCoords()
  const br = obj.getBoundingRect()
  let dx = 0
  let dy = 0

  if (br.left < 0) {
    dx = -br.left
  } else if (br.left + br.width > CANVAS_WIDTH) {
    dx = CANVAS_WIDTH - (br.left + br.width)
  }

  if (br.top < 0) {
    dy = -br.top
  } else if (br.top + br.height > CANVAS_HEIGHT) {
    dy = CANVAS_HEIGHT - (br.top + br.height)
  }

  if (dx === 0 && dy === 0) return

  obj.set({
    left: (obj.left ?? 0) + dx,
    top: (obj.top ?? 0) + dy,
  })
  obj.setCoords()
}

/**
 * Soft-clamp scale so the AABB stays inside the artboard.
 * Remembers the last in-bounds scale (+ left/top — corner handles move both)
 * and reverts when the gesture would overflow. Uses artboard size (CANVAS_*),
 * not the zoomed viewport.
 */
function constrainScaleToArtboard(obj: FabricObject): void {
  const engine = obj as EngineObject
  if (isSmartGuideObject(obj)) return
  if (engine.layerRole === "background") return
  if (engine.isSoftbox || engine.isChipInlineEditor) return

  obj.setCoords()
  const rect = obj.getBoundingRect()

  if (
    rect.left < 0 ||
    rect.top < 0 ||
    rect.left + rect.width > CANVAS_WIDTH ||
    rect.top + rect.height > CANVAS_HEIGHT
  ) {
    obj.set({
      scaleX: engine.lastGoodScaleX ?? obj.scaleX,
      scaleY: engine.lastGoodScaleY ?? obj.scaleY,
      left: engine.lastGoodLeft ?? obj.left,
      top: engine.lastGoodTop ?? obj.top,
    })
    obj.setCoords()
  } else {
    engine.lastGoodScaleX = obj.scaleX
    engine.lastGoodScaleY = obj.scaleY
    engine.lastGoodLeft = obj.left
    engine.lastGoodTop = obj.top
  }
}

function applySmartSnap(
  canvas: FabricCanvas,
  moving: EngineObject,
  lastGuideSigRef: { current: string }
): void {
  if (!moving.layerId || moving.layerRole === "background") return
  const rect = moving.getBoundingRect()
  const movingBounds = boundsFromRect(rect)
  const { dx, dy, guides } = snapMoveToTargets(
    movingBounds,
    collectSnapTargets(canvas, moving)
  )
  if (dx !== 0 || dy !== 0) {
    moving.set({
      left: (moving.left ?? 0) + dx,
      top: (moving.top ?? 0) + dy,
    })
    moving.setCoords()
  }
  // Snap can nudge past the edge — re-clamp without clearing guides.
  constrainObjectToArtboard(moving)
  paintSmartGuides(canvas, guides, lastGuideSigRef)
}

async function safeBuildLayer(
  layer: CanvasLayer,
  builder: (layer: CanvasLayer) => Promise<EngineObject> | EngineObject
): Promise<EngineObject | null> {
  try {
    return await builder(layer)
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[fabric-canvas] layer build failed", layer.id, err)
    }
    // Reset corrupt transform/style, then retry once with store defaults.
    try {
      resetLayerToDefaults(layer.id)
      const recovered =
        useEditorStore.getState().layers.find((l) => l.id === layer.id) ?? layer
      return await builder(recovered)
    } catch (retryErr) {
      if (process.env.NODE_ENV !== "production") {
        console.error(
          "[fabric-canvas] layer rebuild after reset failed",
          layer.id,
          retryErr
        )
      }
      return null
    }
  }
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function clampLayerPosition(
  x: number,
  y: number,
  elW: number,
  elH: number
): { x: number; y: number } {
  const maxX = Math.max(0, 100 - Math.max(0, elW))
  const maxY = Math.max(0, 100 - Math.max(0, elH))
  return {
    x: clamp(x, 0, maxX),
    y: clamp(y, 0, maxY),
  }
}

function layerDefaults(layer: CanvasLayer) {
  if (layer.type === "image") {
    return {
      x: layer.x ?? 27,
      y: layer.y ?? 23,
      width: layer.width ?? 36.68,
      height: layer.height ?? 64,
      scale: layer.scale ?? 1,
      rotation: layer.rotation ?? 0,
    }
  }
  if (layer.type === "text") {
    return {
      x: layer.x ?? 8,
      y: layer.y ?? 68,
      width: layer.width ?? 84,
      height: layer.height,
      scale: layer.scale ?? 1,
      rotation: layer.rotation ?? 0,
    }
  }
  return {
    x: layer.x ?? 50,
    y: layer.y ?? 50,
    width: layer.width,
    height: layer.height,
    scale: layer.scale ?? 1,
    rotation: layer.rotation ?? 0,
  }
}

function fitImageLayerBox(
  naturalW: number,
  naturalH: number,
  maxWidthPct: number,
  maxHeightPct: number
): { width: number; height: number } {
  const widthOverHeight =
    (Math.max(1, naturalW) / Math.max(1, naturalH)) *
    (CANVAS_HEIGHT / CANVAS_WIDTH)
  let width = maxWidthPct
  let height = width / widthOverHeight
  if (height > maxHeightPct) {
    height = maxHeightPct
    width = height * widthOverHeight
  }
  return {
    width: Math.round(width * 100) / 100,
    height: Math.round(height * 100) / 100,
  }
}

function pctToPx(pct: number, dim: number) {
  return (pct / 100) * dim
}

function pxToPct(px: number, dim: number) {
  return (px / dim) * 100
}

/**
 * Photo-add placement: scale to 80% of artboard height and center.
 * Artboard coords (CANVAS_HEIGHT) are the design space; DOM canvas height is the viewport.
 */
function fitProductPhotoToArtboard(
  naturalW: number,
  naturalH: number
): { width: number; height: number; x: number; y: number; scale: number } {
  const nw = Math.max(1, naturalW)
  const nh = Math.max(1, naturalH)
  const scale = (CANVAS_HEIGHT * 0.8) / nh
  const widthPct = pxToPct(nw * scale, CANVAS_WIDTH)
  const heightPct = pxToPct(nh * scale, CANVAS_HEIGHT)
  return {
    width: Math.round(widthPct * 100) / 100,
    height: Math.round(heightPct * 100) / 100,
    x: Math.round(((100 - widthPct) / 2) * 100) / 100,
    y: Math.round(((100 - heightPct) / 2) * 100) / 100,
    scale,
  }
}

function markObject(
  obj: FabricObject,
  layerId: string,
  layerRole: LayerRole
): EngineObject {
  const engine = obj as EngineObject
  engine.layerId = layerId
  engine.layerRole = layerRole
  return engine
}

function findByLayerId(canvas: FabricCanvas, layerId: string) {
  return canvas
    .getObjects()
    .find((o) => (o as EngineObject).layerId === layerId) as
    | EngineObject
    | undefined
}

/** Wait until the underlying HTMLImageElement is fully decoded for paint. */
async function awaitFabricImageDecoded(img: FabricImage): Promise<void> {
  const el =
    (typeof img.getElement === "function" ? img.getElement() : null) ??
    (
      img as FabricImage & {
        _element?: HTMLImageElement | HTMLCanvasElement | HTMLVideoElement
      }
    )._element
  if (!el || el instanceof HTMLCanvasElement || el instanceof HTMLVideoElement) {
    return
  }
  if (typeof el.decode === "function") {
    try {
      await el.decode()
    } catch {
      // decode() can reject for SVG data-URLs in some browsers; onload already fired.
    }
  }
  // Zero-size SVG decode race — yield a frame so naturalWidth settles.
  if (!(img.width > 0 && img.height > 0) || !(el.naturalWidth > 0)) {
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve())
    })
  }
}

async function loadImage(url: string): Promise<FabricImage> {
  const isLocal =
    url.startsWith("data:") ||
    url.startsWith("blob:") ||
    url.startsWith("/")
  // Fabric v6: fromURL returns a Promise (callback form is legacy).
  // Always await the Promise so badge/product bitmaps exist before Group layout.
  let img: FabricImage
  if (isLocal) {
    img = await FabricImage.fromURL(url)
  } else {
    try {
      img = await FabricImage.fromURL(url, { crossOrigin: "anonymous" })
    } catch {
      img = await FabricImage.fromURL(url)
    }
  }
  await awaitFabricImageDecoded(img)
  img.set({ imageSmoothing: true, objectCaching: false, dirty: true })
  return img
}

/** Fabric v6: stack methods live on the canvas (`bringObjectToFront`). */
function bringEngineObjectToFront(
  canvas: FabricCanvas,
  obj: FabricObject
): void {
  const withV6 = canvas as FabricCanvas & {
    bringObjectToFront?: (object: FabricObject) => boolean
  }
  if (typeof withV6.bringObjectToFront === "function") {
    withV6.bringObjectToFront(obj)
    return
  }
  const withLegacy = canvas as FabricCanvas & {
    bringToFront?: (object: FabricObject) => FabricCanvas
  }
  if (typeof withLegacy.bringToFront === "function") {
    withLegacy.bringToFront(obj)
  }
}

/**
 * Badge IText metrics are wrong if next/font faces are still loading — groups land
 * in the scene but stay invisible until a settings tweak re-layouts them.
 * `document.fonts.ready` alone is not enough: next/font faces may still be idle
 * until explicitly requested via `fonts.load` for the canvas-measured sizes.
 */
async function awaitDocumentFontsReady(): Promise<void> {
  if (typeof document === "undefined" || !document.fonts?.ready) return
  try {
    await document.fonts.ready
    const family = resolveFabricFontFamily("Inter")
    const hi = CHIP_SOURCE_SCALE
    await Promise.all([
      document.fonts.load(`600 ${16 * hi}px ${family}`),
      document.fonts.load(`600 ${18 * hi}px ${family}`),
      document.fonts.load(`400 ${Math.max(11 * hi, 16 * hi * 0.72)}px ${family}`),
    ])
  } catch {
    // Font readiness can reject in rare environments; paint with fallbacks.
  }
}

function isBadgeGroupObject(obj: FabricObject): boolean {
  return (
    obj instanceof Group && (obj as EngineObject).chipSourceScale != null
  )
}

/** True when store has visible chips/text that are missing from Fabric. */
function canvasMissingInfographicLayers(
  canvas: FabricCanvas,
  layers: CanvasLayer[]
): boolean {
  for (const layer of layers) {
    if (!layer.visible || layer.type === "background") continue
    if (layer.type === "image" || layer.id === "layer_product") continue
    if (layer.type === "text" || (layer.type === "shape" && layer.chip)) {
      if (!findByLayerId(canvas, layer.id)) return true
    }
  }
  return false
}

/**
 * Commit pre-built badge Groups onto the canvas ONLY after fonts are paint-ready.
 * Forces dirty/coords + deferred renderAll so hydrate paint sticks on first entry.
 */
async function commitBadgeGroupsToCanvas(
  canvas: FabricCanvas,
  badges: FabricObject[]
): Promise<void> {
  if (badges.length === 0) return

  await awaitDocumentFontsReady()
  if (!isFabricCanvasAlive(canvas)) return

  for (const badgeGroup of badges) {
    if (badgeGroup instanceof Group) {
      for (const child of badgeGroup.getObjects()) {
        if (isChipTextObjectType(child.type)) {
          const text = child as Textbox
          if (typeof text.initDimensions === "function") {
            text.initDimensions()
          }
        }
        child.set({ dirty: true })
        child.setCoords()
      }
    }
    badgeGroup.set({ dirty: true })
    badgeGroup.setCoords()
    canvas.add(badgeGroup)
    bringEngineObjectToFront(canvas, badgeGroup)
  }

  // Layout after fonts.load — glyph metrics are stable; skip if group already correct.
  for (const badgeGroup of badges) {
    if (!isBadgeGroupObject(badgeGroup)) continue
    updateBadgeLayout(badgeGroup as Group)
  }

  canvas.calcOffset()
  canvas.requestRenderAll()

  window.setTimeout(() => {
    if (!isFabricCanvasAlive(canvas)) return
    canvas.forEachObject((obj) => {
      obj.set({ dirty: true })
      obj.setCoords()
    })
    canvas.renderAll()
  }, 200)
}

/**
 * Structural fingerprint — excludes transforms AND softbox (softbox updates in-place).
 * Chip label/subtitle/colors/blur/opacity are patched onto existing objects; including
 * them here would rebuild the whole scene on every color-picker frame (~5fps stutter).
 */
function structureKey(args: {
  layers: CanvasLayer[]
  productPreviewUrl: string | null
  backgroundPreviewUrl: string | null
  generationEpoch: number
}): string {
  return JSON.stringify({
    productPreviewUrl: args.productPreviewUrl,
    backgroundPreviewUrl: args.backgroundPreviewUrl,
    generationEpoch: args.generationEpoch,
    layers: args.layers.map((l) => {
      const chip = l.chip
      return {
        id: l.id,
        type: l.type,
        visible: l.visible,
        locked: l.locked,
        zIndex: l.zIndex,
        text: l.text,
        textStyle: l.textStyle,
        // Structural chip fields only — colors/blur/content sync in-place.
        chip: chip
          ? {
              borderRadius: chip.borderRadius,
              iconId: chip.iconId,
              variant: chip.variant,
              hasSubtitle: Boolean(chip.subtitle),
            }
          : undefined,
      }
    }),
  })
}

function findBackgroundGroup(canvas: FabricCanvas): Group | null {
  const bg = canvas
    .getObjects()
    .find((o) => (o as EngineObject).layerId === "layer_bg")
  return bg instanceof Group ? bg : null
}

function findSoftboxImage(canvas: FabricCanvas): FabricImage | null {
  const bg = findBackgroundGroup(canvas)
  if (!bg) return null
  const hit = bg.getObjects().find((o) => (o as EngineObject).isSoftbox)
  return hit instanceof FabricImage ? hit : null
}

function disposeBuiltObjects(objects: FabricObject[]): void {
  for (const obj of objects) {
    try {
      void obj.dispose()
    } catch {
      // Concurrent dispose / already detached from canvas.
    }
  }
  objects.length = 0
}

function isFabricCanvasAlive(
  canvas: FabricCanvas | null | undefined
): canvas is FabricCanvas {
  if (!canvas || canvas.disposed || canvas.destroyed) return false
  try {
    const ctx = canvas.getContext()
    return Boolean(ctx)
  } catch {
    return false
  }
}

/**
 * Keep Fabric softbox bitmap in sync for PNG export, but never show it live.
 * Live lighting is exclusively the CSS SoftboxLightOverlay (one formula, one path).
 * Showing both CSS + Fabric wash stacks and darkens the artboard on slider commit.
 */
function applySoftboxToFabric(
  canvas: FabricCanvas,
  softbox: SoftboxSettings
): void {
  try {
    if (!isFabricCanvasAlive(canvas)) return

    const img = findSoftboxImage(canvas)
    if (!img) return
    const bg = findBackgroundGroup(canvas)

    const el = img.getElement()
    if (!(el instanceof HTMLCanvasElement)) return
    if (el.width !== CANVAS_WIDTH || el.height !== CANVAS_HEIGHT) {
      el.width = CANVAS_WIDTH
      el.height = CANVAS_HEIGHT
    }
    if (!paintSoftboxInPlace(el, softbox)) return

    // Hidden for live view — CSS overlay owns the visible light.
    img.set({
      objectCaching: true,
      opacity: 0,
      dirty: true,
    })
    bg?.set({ objectCaching: true, dirty: true })
    img.setCoords()
    bg?.setCoords()
    canvas.backgroundColor = "rgba(0,0,0,0)"
    if (isFabricCanvasAlive(canvas)) canvas.requestRenderAll()
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[fabric-canvas] softbox redraw failed", err)
    }
  }
}

/**
 * Apply current softbox/lighting from store to the Fabric scene.
 * Must run on mount + after scene rebuild — not only when a UI slider fires onChange.
 */
function applyLightingEffects(
  canvas: FabricCanvas,
  softbox: SoftboxSettings = useEditorStore.getState().softbox
): void {
  // Transparent artboard so CSS SoftboxLightOverlay wash shows through.
  canvas.backgroundColor = "rgba(0,0,0,0)"
  applySoftboxToFabric(canvas, softbox)
}

/**
 * Force objects + lighting onto the visible surface after async load / rebuild.
 * Without this, layers can exist in memory while the artboard stays dark until a slider move.
 */
function forceCanvasVisualSync(canvas: FabricCanvas): void {
  if (!isFabricCanvasAlive(canvas)) return
  canvas.forEachObject((obj) => {
    obj.set({ dirty: true })
    obj.setCoords()
  })
  canvas.calcOffset()
  applyLightingEffects(canvas, useEditorStore.getState().softbox)
  canvas.requestRenderAll()
  window.setTimeout(() => {
    if (!isFabricCanvasAlive(canvas)) return
    canvas.forEachObject((obj) => {
      obj.set({ dirty: true })
      obj.setCoords()
    })
    canvas.renderAll()
  }, 200)
}

/** Briefly reveal Fabric softbox for toDataURL export, then restore CSS-only live mode. */
async function withFabricSoftboxVisibleForExport<T>(
  canvas: FabricCanvas,
  run: () => Promise<T>
): Promise<T> {
  const img = findSoftboxImage(canvas)
  if (img) {
    img.set({ opacity: 1 })
    canvas.backgroundColor = "#0d0f12"
    canvas.requestRenderAll()
  }
  try {
    return await run()
  } finally {
    if (isFabricCanvasAlive(canvas)) {
      const current = findSoftboxImage(canvas)
      if (current) current.set({ opacity: 0 })
      canvas.backgroundColor = "rgba(0,0,0,0)"
      canvas.requestRenderAll()
    }
  }
}

/**
 * Single live lighting path — CSS wash (under canvas) + soft-light blend (over).
 * Always driven by `softbox` state (drag and idle identical). Stable DOM — never
 * mount/unmount on slider ticks; styles update imperatively via store.subscribe.
 * `paintKey` forces an immediate re-paint after canvas mount / scene rebuild
 * (does not wait for a softbox slider onChange).
 */
function SoftboxLightOverlay({
  frame,
  paintKey = 0,
}: {
  frame: FabricViewportFrame | null
  paintKey?: number
}) {
  const washRef = useRef<HTMLDivElement>(null)
  const blendRef = useRef<HTMLDivElement>(null)
  const frameRef = useRef(frame)
  const paintOverlayRef = useRef<() => void>(() => {})

  useLayoutEffect(() => {
    const paintOverlay = () => {
      const wash = washRef.current
      const blend = blendRef.current
      if (!wash || !blend) return

      const state = useEditorStore.getState()
      const f = frameRef.current
      const softbox = state.softbox

      const applyBox = (el: HTMLDivElement) => {
        if (!f) return
        el.style.left = `${f.left}px`
        el.style.top = `${f.top}px`
        el.style.width = `${f.width}px`
        el.style.height = `${f.height}px`
      }

      applyBox(wash)
      applyBox(blend)

      if (f == null) {
        wash.hidden = true
        blend.hidden = true
        wash.style.visibility = "hidden"
        blend.style.visibility = "hidden"
        return
      }

      let washStyle: CSSProperties | null = null
      let blendStyle: CSSProperties | null = null
      try {
        // Studio wash under the transparent Fabric softbox; skip when AI bg covers it.
        if (!state.backgroundPreviewUrl) {
          washStyle = softboxOverlayStyle(softbox)
        }
        blendStyle = softboxLightBlendStyle(softbox)
      } catch {
        wash.hidden = true
        blend.hidden = true
        return
      }

      const assignStyle = (el: HTMLDivElement, style: CSSProperties | null) => {
        if (!style) {
          el.hidden = true
          el.style.visibility = "hidden"
          return
        }
        el.hidden = false
        el.style.visibility = "visible"
        el.style.transition = "none"
        el.style.transitionProperty = "none"
        el.style.animation = "none"
        el.style.pointerEvents = "none"
        if (style.backgroundColor != null) {
          el.style.backgroundColor = String(style.backgroundColor)
        } else {
          el.style.backgroundColor = ""
        }
        el.style.backgroundImage =
          style.backgroundImage != null ? String(style.backgroundImage) : ""
        el.style.opacity = style.opacity != null ? String(style.opacity) : ""
        el.style.mixBlendMode =
          style.mixBlendMode != null ? String(style.mixBlendMode) : "normal"
        el.style.boxShadow =
          style.boxShadow != null ? String(style.boxShadow) : "none"
        el.style.filter = style.filter != null ? String(style.filter) : "none"
      }

      assignStyle(wash, washStyle)
      assignStyle(blend, blendStyle)
    }

    paintOverlayRef.current = paintOverlay
    // Immediate paint on mount from current softbox state — never wait for slider onChange.
    frameRef.current = frame
    paintOverlay()
    const unsub = useEditorStore.subscribe((state, prev) => {
      if (
        state.softbox === prev.softbox &&
        state.backgroundPreviewUrl === prev.backgroundPreviewUrl
      ) {
        return
      }
      paintOverlayRef.current()
    })
    return () => {
      unsub()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only; frame/paintKey below
  }, [])

  useLayoutEffect(() => {
    frameRef.current = frame
    paintOverlayRef.current()
  }, [frame, paintKey])

  return (
    <>
      <div
        ref={washRef}
        aria-hidden
        hidden
        data-export-chrome="true"
        data-softbox-overlay="wash"
        className="softbox-light-overlay pointer-events-none absolute z-0"
        style={{ transition: "none", transitionProperty: "none" }}
      />
      <div
        ref={blendRef}
        aria-hidden
        hidden
        data-export-chrome="true"
        data-softbox-overlay="blend"
        className="softbox-light-overlay pointer-events-none absolute z-[2]"
        style={{
          transition: "none",
          transitionProperty: "none",
          mixBlendMode: "soft-light",
        }}
      />
    </>
  )
}

async function buildBackgroundLayer(args: {
  softbox: SoftboxSettings
  backgroundPreviewUrl: string | null
}): Promise<Group> {
  // Per-layer canvas — never reuse the export scratch buffer as a Fabric element.
  const paint = createSoftboxSourceCanvas(
    args.softbox,
    CANVAS_WIDTH,
    CANVAS_HEIGHT
  )
  const softboxImg = new FabricImage(paint, {
    left: CANVAS_WIDTH / 2,
    top: CANVAS_HEIGHT / 2,
    originX: "center",
    originY: "center",
    selectable: false,
    evented: false,
    objectCaching: true,
    // Live light is CSS SoftboxLightOverlay — Fabric softbox is export-only.
    opacity: 0,
  })
  ;(softboxImg as EngineObject).isSoftbox = true
  softboxImg.scaleToWidth(CANVAS_WIDTH)

  const children: FabricObject[] = [softboxImg]

  if (args.backgroundPreviewUrl) {
    try {
      const ai = await loadImage(args.backgroundPreviewUrl)
      const coverScale = Math.max(
        CANVAS_WIDTH / Math.max(1, ai.width ?? 1),
        CANVAS_HEIGHT / Math.max(1, ai.height ?? 1)
      )
      ai.set({
        left: CANVAS_WIDTH / 2,
        top: CANVAS_HEIGHT / 2,
        originX: "center",
        originY: "center",
        scaleX: coverScale,
        scaleY: coverScale,
        selectable: false,
        evented: false,
        objectCaching: true,
      })
      children.push(ai)
    } catch {
      // keep softbox-only background
    }
  }

  const group = new Group(children, {
    left: 0,
    top: 0,
    originX: "left",
    originY: "top",
    selectable: false,
    evented: false,
    hoverCursor: "default",
    subTargetCheck: false,
    objectCaching: true,
  })
  markObject(group, "layer_bg", "background")
  return group
}

async function buildProductObject(
  layer: CanvasLayer,
  productPreviewUrl: string | null
): Promise<EngineObject> {
  const defs = layerDefaults(layer)
  // Never allow a 0×0 box — that paints a black void after fromURL.
  const boxW = Math.max(1, pctToPx(defs.width ?? 36.68, CANVAS_WIDTH))
  const boxH = Math.max(1, pctToPx(defs.height ?? 80, CANVAS_HEIGHT))
  const centerX = pctToPx(defs.x, CANVAS_WIDTH) + (boxW * defs.scale) / 2
  const centerY = pctToPx(defs.y, CANVAS_HEIGHT) + (boxH * defs.scale) / 2

  const common: Partial<FabricObjectProps> = {
    originX: "center",
    originY: "center",
    left: centerX,
    top: centerY,
    angle: defs.rotation,
    opacity: layer.opacity,
    selectable: !layer.locked,
    evented: !layer.locked,
    hasControls: true,
    lockScalingFlip: true,
    objectCaching: true,
  }

  if (!productPreviewUrl) {
    const placeholder = new Rect({
      ...common,
      width: boxW,
      height: boxH,
      fill: "rgba(255,255,255,0.03)",
      stroke: "rgba(255,255,255,0.15)",
      strokeDashArray: [12, 8],
      rx: 16,
      ry: 16,
      scaleX: defs.scale,
      scaleY: defs.scale,
    })
    return markObject(placeholder, layer.id, "product")
  }

  try {
    // Fabric v6: fromURL is Promise-based (legacy callback form removed).
    const img = await loadImage(productPreviewUrl)
    const nw = Math.max(1, img.width || 1)
    const nh = Math.max(1, img.height || 1)

    // Photo-add algorithm: scale to 80% of artboard height, then apply store box if present.
    const photoScale = (CANVAS_HEIGHT * 0.8) / nh
    const useStoreBox = layer.width != null && layer.height != null
    if (useStoreBox) {
      img.set({
        ...common,
        width: nw,
        height: nh,
        scaleX: Math.max(0.001, (boxW / nw) * defs.scale),
        scaleY: Math.max(0.001, (boxH / nh) * defs.scale),
      })
    } else {
      img.set({
        ...common,
        left: CANVAS_WIDTH / 2,
        top: CANVAS_HEIGHT / 2,
        width: nw,
        height: nh,
      })
      img.scale(Math.max(0.001, photoScale * defs.scale))
    }
    img.setCoords()
    return markObject(img, layer.id, "product")
  } catch {
    const placeholder = new Rect({
      ...common,
      width: boxW,
      height: boxH,
      fill: "rgba(255,80,80,0.06)",
      stroke: "rgba(255,120,120,0.35)",
      strokeDashArray: [10, 8],
      rx: 16,
      ry: 16,
      scaleX: defs.scale,
      scaleY: defs.scale,
    })
    return markObject(placeholder, layer.id, "product")
  }
}

function applyTextStyle(text: IText, style: TextLayerStyle | undefined) {
  const ts = style ?? DEFAULT_TEXT_STYLE
  text.set({
    fontFamily: resolveFabricFontFamily(ts.fontFamily),
    fontSize: ts.fontSize,
    fontWeight: String(ts.fontWeight),
    fill: ts.color,
    stroke: ts.strokeWidth > 0 ? ts.strokeColor : undefined,
    strokeWidth: ts.strokeWidth > 0 ? ts.strokeWidth : 0,
    shadow: ts.shadowEnabled
      ? new Shadow({
          color: ts.shadowColor,
          blur: ts.shadowBlur,
          offsetX: ts.shadowOffsetX,
          offsetY: ts.shadowOffsetY,
        })
      : null,
  })
}

function buildTextObject(layer: CanvasLayer): IText {
  const defs = layerDefaults(layer)
  const text = new IText(layer.text ?? "", {
    left: pctToPx(defs.x, CANVAS_WIDTH),
    top: pctToPx(defs.y, CANVAS_HEIGHT),
    originX: "left",
    originY: "top",
    padding: 0,
    width: pctToPx(defs.width ?? 84, CANVAS_WIDTH),
    scaleX: defs.scale,
    scaleY: defs.scale,
    angle: defs.rotation,
    opacity: layer.opacity,
    selectable: !layer.locked,
    evented: !layer.locked,
    editable: !layer.locked,
    hasControls: true,
    lockScalingFlip: true,
    // Live text stays uncached so scale/edit stays sharp (see ensureFabricQualityDefaults).
    objectCaching: false,
  })
  applyTextStyle(text, layer.textStyle)
  return markObject(text, layer.id, "infographic") as IText
}

async function buildChipObject(layer: CanvasLayer): Promise<Group> {
  // Wait for document fonts + vector icon decode before measuring Textbox / Group.
  await awaitDocumentFontsReady()

  const chip = layer.chip!
  const defs = layerDefaults(layer)
  const isGlass = chip.variant === "glass"
  const fg =
    chip.textColor ??
    (isGlass || (chip.blur ?? 0) > 0
      ? "#FFFFFF"
      : chipTextColor(chip.bgColor))

  // Geometry at CHIP_SOURCE_SCALE×; group scaleX/Y brings it back to logical size.
  const hi = CHIP_SOURCE_SCALE
  const padX = (isGlass ? 18 : 14) * hi
  const padY = (isGlass ? 14 : 10) * hi
  const iconSize = (isGlass ? 22 : 18) * hi
  const labelSize = (isGlass ? 18 : 16) * hi
  const gap = 10 * hi
  const radius = (chip.borderRadius ?? (isGlass ? 14 : 10)) * hi
  // SVG rasterized well above on-canvas icon box (extra 2× before group downscale).
  const iconSrcPx = Math.max(192, Math.round(iconSize * 2))

  // Promise-wrap icon load (FabricImage.fromURL) so the Group is never measured
  // against an empty / half-decoded SVG bitmap on first hydrate.
  const icon = await loadImage(chipIconDataUrl(chip.iconId, fg, iconSrcPx))
  icon.set({
    originX: "left",
    originY: "center",
    left: padX,
    top: 0,
    selectable: false,
    evented: false,
    objectCaching: false,
    imageSmoothing: true,
    dirty: true,
  })
  icon.scaleToWidth(iconSize)
  icon.setCoords()
  ;(icon as EngineObject).chipPart = "icon"

  const chipFont = resolveFabricFontFamily("Inter")
  const textLocked = Boolean(layer.locked)
  const placeScale = defs.scale / hi
  const groupLeft = pctToPx(defs.x, CANVAS_WIDTH)
  const maxTextWidth = chipTextWidthBarrier({
    hi,
    padX,
    iconSize,
    gap,
    groupLeft,
    groupScaleX: placeScale,
  })
  // Text uses left/top origin — center origin shifts the edit selection frame.
  // Vertical centering is done via top offsets, not originY: "center".
  // Nested Textbox is interactive (subTargetCheck) so dblclick can enterEditing.
  const label = new Textbox(chip.label, {
    left: padX + iconSize + gap,
    top: 0,
    originX: "left",
    originY: "top",
    padding: 0,
    fontFamily: chipFont,
    fontSize: labelSize,
    fontWeight: "600",
    fill: fg,
    selectable: !textLocked,
    evented: !textLocked,
    editable: !textLocked,
    hasControls: false,
    lockMovementX: true,
    lockMovementY: true,
    objectCaching: false,
    width: maxTextWidth,
    splitByGrapheme: false,
  })
  ;(label as EngineObject).chipPart = "label"
  ;(label as EngineObject).layerId = layer.id
  ;(label as EngineObject).layerRole = "infographic"
  fitChipTextboxWidth(label, maxTextWidth)

  // Subtitle grows downward only — never upward into the title.
  const textStackGap = 5 * hi
  const subtitle = chip.subtitle
    ? new Textbox(chip.subtitle, {
        left: padX + iconSize + gap,
        top: 0,
        originX: "left",
        originY: "top",
        padding: 0,
        fontFamily: chipFont,
        fontSize: Math.max(11 * hi, labelSize * 0.72),
        fontWeight: "400",
        fill: fg,
        opacity: 0.7,
        selectable: !textLocked,
        evented: !textLocked,
        editable: !textLocked,
        hasControls: false,
        lockMovementX: true,
        lockMovementY: true,
        objectCaching: false,
        width: maxTextWidth,
        splitByGrapheme: false,
      })
    : null
  if (subtitle) {
    ;(subtitle as EngineObject).chipPart = "subtitle"
    ;(subtitle as EngineObject).layerId = layer.id
    ;(subtitle as EngineObject).layerRole = "infographic"
    fitChipTextboxWidth(subtitle, maxTextWidth)
  }

  await Promise.resolve()

  // Stack from the top of the plate so Enter expands downward only.
  // Fit width first (content → canvas barrier), then measure height for the plate.
  const labelW = fitChipTextboxWidth(label, maxTextWidth)
  const subtitleW = subtitle ? fitChipTextboxWidth(subtitle, maxTextWidth) : 0
  const labelH = label.height ?? labelSize
  const subtitleH = subtitle
    ? (subtitle.height ?? Math.max(11 * hi, labelSize * 0.72))
    : 0
  const contentH =
    chip.subtitle && subtitle ? labelH + textStackGap + subtitleH : labelH
  const boxH = contentH + padY * 2
  const contentTop = -boxH / 2 + padY

  label.set({ originY: "top", top: contentTop, width: labelW })
  if (chip.subtitle && subtitle) {
    const titleTop = label.top ?? contentTop
    subtitle.set({
      originY: "top",
      top: titleTop + labelH + textStackGap,
      width: subtitleW,
    })
  }

  // Plate tracks text width; wraps (and grows down) only at the canvas barrier.
  const contentW = Math.min(maxTextWidth, Math.max(labelW, subtitleW, 80 * hi))
  const boxW = padX + iconSize + gap + contentW + padX

  const bg = new Rect({
    left: 0,
    top: -boxH / 2,
    width: boxW,
    height: boxH,
    rx: radius,
    ry: radius,
    fill: chip.bgColor,
    stroke: isGlass ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.1)",
    strokeWidth: hi,
    selectable: false,
    evented: false,
    objectCaching: false,
  })
  ;(bg as EngineObject).chipPart = "bg"

  const children: FabricObject[] = [bg, icon, label]
  if (subtitle) children.push(subtitle)

  const group = new Group(children, {
    left: groupLeft,
    top: pctToPx(defs.y, CANVAS_HEIGHT),
    originX: "left",
    originY: "top",
    scaleX: placeScale,
    scaleY: placeScale,
    angle: defs.rotation,
    opacity: layer.opacity,
    selectable: !layer.locked,
    evented: !layer.locked,
    hasControls: true,
    lockScalingFlip: true,
    // Allow targeting nested Textbox for on-canvas label editing.
    subTargetCheck: true,
    interactive: true,
    objectCaching: false,
  })
  const marked = markObject(group, layer.id, "infographic")
  marked.chipSourceScale = hi
  // Dirty + coords before canvas.add — metrics are stable after fonts.ready + icon load.
  marked.set({ dirty: true })
  marked.setCoords()
  rememberChipIconFg(layer.id, fg)
  return marked as Group
}

function chipPartOf(
  obj: FabricObject,
  part: ChipPart
): FabricObject | undefined {
  return (obj as EngineObject).chipPart === part ? obj : undefined
}

/** Parent badge Group for a nested chip text child (interactive groups). */
function chipGroupOf(obj: FabricObject): Group | null {
  const parent = obj.group ?? obj.parent
  return parent instanceof Group ? parent : null
}

function isChipTextPart(obj: FabricObject | undefined): obj is Textbox & EngineObject {
  if (!obj || !isChipTextObjectType(obj.type)) return false
  const part = (obj as EngineObject).chipPart
  return part === "label" || part === "subtitle"
}

/** Resolve chip draft for layout metrics (glass padding, etc.). */
function chipDraftOf(group: Group): FeatureChipDraft | undefined {
  const layerId = (group as EngineObject).layerId
  if (!layerId) return undefined
  return useEditorStore.getState().layers.find((l) => l.id === layerId)?.chip
}

/**
 * Recalculate badge plate size + relative child coords after text length changes.
 * Preserves absolute canvas left/top across addWithUpdate / triggerLayout
 * (Fabric otherwise resets the group to 0,0).
 */
function updateBadgeLayout(group: Group): void {
  // Snapshot BEFORE child mutations — Fabric auto-layout on nested text
  // `changed` / addWithUpdate can zero the group's canvas left/top.
  const absoluteLeft = group.left ?? 0
  const absoluteTop = group.top ?? 0

  const hi = Math.max(
    1,
    (group as EngineObject).chipSourceScale ?? CHIP_SOURCE_SCALE
  )
  const chip = chipDraftOf(group)
  const isGlass = chip?.variant === "glass"
  const padX = (isGlass ? 18 : 14) * hi
  const padY = (isGlass ? 14 : 10) * hi
  const iconSize = (isGlass ? 22 : 18) * hi
  const labelSize = (isGlass ? 18 : 16) * hi
  const gap = 10 * hi
  /** Vertical gap between title and subtitle (≈5px logical). */
  const textStackGap = 5 * hi
  const padding = padX * 2 + gap
  const maxTextWidth = chipTextWidthBarrier({
    hi,
    padX,
    iconSize,
    gap,
    groupLeft: absoluteLeft,
    groupScaleX: group.scaleX ?? 1,
  })

  const children = group.getObjects()
  const bg = children.find((o) => chipPartOf(o, "bg")) as Rect | undefined
  const icon = children.find((o) => chipPartOf(o, "icon"))
  const label = children.find((o) => chipPartOf(o, "label")) as
    | Textbox
    | undefined
  const subtitle = children.find((o) => chipPartOf(o, "subtitle")) as
    | Textbox
    | undefined

  // Grow with content; wrap only after hitting the canvas barrier.
  const textWidth = label ? fitChipTextboxWidth(label, maxTextWidth) : 80 * hi
  const subtitleWidth = subtitle
    ? fitChipTextboxWidth(subtitle, maxTextWidth)
    : 0

  const iconWidth =
    icon && typeof icon.getScaledWidth === "function"
      ? icon.getScaledWidth()
      : iconSize
  const newWidth = Math.max(textWidth, subtitleWidth) + iconWidth + padding
  const hasSubtitle = Boolean(subtitle)

  const labelH = label?.height ?? labelSize
  const subtitleH = subtitle
    ? (subtitle.height ?? Math.max(11 * hi, labelSize * 0.72))
    : 0
  // Plate grows with real text height (multi-line wrap / Enter expands downward).
  const contentH = hasSubtitle ? labelH + textStackGap + subtitleH : labelH
  const boxH = contentH + padY * 2
  const contentTop = -boxH / 2 + padY

  // Local coords centered on (0,0) — matches Fabric group space after layout.
  const left0 = -newWidth / 2
  const textLeft = left0 + padX + iconWidth + gap

  if (bg) {
    bg.set({
      originX: "left",
      originY: "top",
      left: left0,
      top: -boxH / 2,
      width: newWidth,
      height: boxH,
    })
  }

  if (icon) {
    icon.set({
      originX: "left",
      originY: "center",
      left: left0 + padX,
      top: 0,
    })
  }

  if (label) {
    label.set({
      originX: "left",
      originY: "top",
      left: textLeft,
      top: contentTop,
      width: textWidth,
    })
    if (hasSubtitle && subtitle) {
      // Hard top-anchor: subtitle always sits under the title, never overlaps it.
      const titleTop = label.top ?? contentTop
      subtitle.set({
        originX: "left",
        originY: "top",
        left: textLeft,
        top: titleTop + labelH + textStackGap,
        width: subtitleWidth,
      })
    }
  }

  // addWithUpdate / triggerLayout can reset the group's canvas left/top to 0.
  // Restore the absolute position captured at the start of this update.
  const withLegacy = group as Group & { addWithUpdate?: () => void }
  if (typeof withLegacy.addWithUpdate === "function") {
    withLegacy.addWithUpdate()
  } else {
    group.triggerLayout()
  }

  group.set({
    left: absoluteLeft,
    top: absoluteTop,
  })
  group.setCoords()
  group.set("dirty", true)
  group.canvas?.requestRenderAll()
}

/**
 * Update badge label/subtitle on an existing Group — never rebuild the Group.
 * Resizes the background plate and triggers Fabric layout so handles stay correct.
 * Skips layout when text is unchanged (color/opacity scrub must stay cheap).
 */
function applyChipContentInPlace(group: Group, chip: FeatureChipDraft): void {
  const children = group.getObjects()
  const label = children.find((o) => chipPartOf(o, "label")) as
    | Textbox
    | undefined
  const subtitle = children.find((o) => chipPartOf(o, "subtitle")) as
    | Textbox
    | undefined

  let textChanged = false
  if (label && label.text !== chip.label) {
    // Don't clobber in-progress canvas editing.
    if (!(label as Textbox).isEditing) {
      label.set("text", chip.label)
      textChanged = true
    }
  }
  if (subtitle) {
    const next = chip.subtitle ?? ""
    if (subtitle.text !== next && !(subtitle as Textbox).isEditing) {
      subtitle.set("text", next)
      textChanged = true
    }
  }

  if (textChanged) updateBadgeLayout(group)
}

/** Remove leftover top-level chip overlay editors from earlier edit sessions. */
function clearChipInlineEditors(canvas: FabricCanvas) {
  for (const obj of [...canvas.getObjects()]) {
    const engine = obj as EngineObject
    if (!engine.isChipInlineEditor) continue
    if (obj.type === "i-text" && (obj as IText).isEditing) {
      ;(obj as IText).exitEditing()
    }
    if (canvas.getObjects().includes(obj)) {
      canvas.remove(obj)
    }
  }
}

/**
 * Sync Fabric DOM offset + object aCoords when entering inline edit.
 * Stale calcOffset (zoom/fit/layout) makes the blue frame + textarea jump.
 */
function syncTextEditingCoords(canvas: FabricCanvas, text: IText) {
  canvas.calcOffset()
  text.setCoords()
}

function objectToLayerPatch(obj: EngineObject): Partial<CanvasLayer> | null {
  if (!obj.layerId || obj.layerRole === "background") return null

  const sourceScale = Math.max(1, obj.chipSourceScale ?? 1)
  const scaleAvg =
    (((obj.scaleX ?? 1) + (obj.scaleY ?? 1)) / 2) * sourceScale
  const angle = ((obj.angle ?? 0) % 360 + 360) % 360

  if (obj.layerRole === "product") {
    const scaledW = (obj.width ?? 0) * (obj.scaleX ?? 1)
    const scaledH = (obj.height ?? 0) * (obj.scaleY ?? 1)
    const left =
      obj.originX === "center"
        ? (obj.left ?? 0) - scaledW / 2
        : (obj.left ?? 0)
    const top =
      obj.originY === "center"
        ? (obj.top ?? 0) - scaledH / 2
        : (obj.top ?? 0)
    const widthPct = pxToPct(scaledW / Math.max(0.01, scaleAvg), CANVAS_WIDTH)
    const heightPct = pxToPct(scaledH / Math.max(0.01, scaleAvg), CANVAS_HEIGHT)
    const pos = clampLayerPosition(
      pxToPct(left, CANVAS_WIDTH),
      pxToPct(top, CANVAS_HEIGHT),
      widthPct * scaleAvg,
      heightPct * scaleAvg
    )
    return {
      x: Math.round(pos.x * 100) / 100,
      y: Math.round(pos.y * 100) / 100,
      width: Math.round(widthPct * 100) / 100,
      height: Math.round(heightPct * 100) / 100,
      scale: Math.round(scaleAvg * 1000) / 1000,
      rotation: Math.round(angle),
      opacity: obj.opacity ?? 1,
    }
  }

  return {
    x: Math.round(pxToPct(obj.left ?? 0, CANVAS_WIDTH) * 100) / 100,
    y: Math.round(pxToPct(obj.top ?? 0, CANVAS_HEIGHT) * 100) / 100,
    scale: Math.round(scaleAvg * 1000) / 1000,
    rotation: Math.round(angle),
    opacity: obj.opacity ?? 1,
    ...(obj.type === "i-text"
      ? {
          width:
            Math.round(
              pxToPct((obj.width ?? 100) / Math.max(0.01, obj.scaleX ?? 1), CANVAS_WIDTH) *
                100
            ) / 100,
        }
      : {}),
  }
}

function applyTransformFromLayer(obj: EngineObject, layer: CanvasLayer) {
  const defs = layerDefaults(layer)
  if (obj.layerRole === "product") {
    const boxW = pctToPx(defs.width ?? 36.68, CANVAS_WIDTH)
    const boxH = pctToPx(defs.height ?? 64, CANVAS_HEIGHT)
    const centerX = pctToPx(defs.x, CANVAS_WIDTH) + (boxW * defs.scale) / 2
    const centerY = pctToPx(defs.y, CANVAS_HEIGHT) + (boxH * defs.scale) / 2
    const nw = Math.max(1, obj.width ?? 1)
    const nh = Math.max(1, obj.height ?? 1)
    if (obj.type === "image") {
      obj.set({
        left: centerX,
        top: centerY,
        angle: defs.rotation,
        scaleX: (boxW / nw) * defs.scale,
        scaleY: (boxH / nh) * defs.scale,
        opacity: layer.opacity,
      })
    } else {
      obj.set({
        left: centerX,
        top: centerY,
        angle: defs.rotation,
        scaleX: defs.scale,
        scaleY: defs.scale,
        opacity: layer.opacity,
      })
    }
    return
  }

  const sourceScale = Math.max(1, obj.chipSourceScale ?? 1)
  const placeScale = defs.scale / sourceScale
  obj.set({
    left: pctToPx(defs.x, CANVAS_WIDTH),
    top: pctToPx(defs.y, CANVAS_HEIGHT),
    angle: defs.rotation,
    scaleX: placeScale,
    scaleY: placeScale,
    opacity: layer.opacity,
  })
}

function EditorFabricCanvasImpl({ scale }: { scale: number }) {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const flashLayerId = useEditorStore((s) => s.flashLayerId)
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const syncLayerGeometry = useEditorStore((s) => s.syncLayerGeometry)
  const beginHistoryTransaction = useEditorStore(
    (s) => s.beginHistoryTransaction
  )
  const commitHistoryTransaction = useEditorStore(
    (s) => s.commitHistoryTransaction
  )
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const backgroundPreviewUrl = useEditorStore((s) => s.backgroundPreviewUrl)
  const generationEpoch = useEditorStore((s) => s.generationEpoch)
  const busyKind = useEditorStore((s) => s.busyKind)
  const busyProgress = useEditorStore((s) => s.busyProgress)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const zoomMode = useEditorStore((s) => s.zoomMode)

  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fabricRef = useRef<FabricCanvas | null>(null)
  const syncViewportRef = useRef<() => FabricViewportFrame | null>(() => null)
  const [artboardFrame, setArtboardFrame] = useState<FabricViewportFrame | null>(
    null
  )
  /** True while Fabric is writing into Zustand (skip store→Fabric echo). */
  const writingStoreRef = useRef(false)
  /** True for the whole pointer gesture — Fabric is source of truth mid-drag. */
  const interactingRef = useRef(false)
  /** Second click (already selected, no drag) enters text edit. */
  const clickEditRef = useRef<{
    layerId: string | null
    wasAlreadySelected: boolean
    moved: boolean
  }>({ layerId: null, wasAlreadySelected: false, moved: false })
  const fittedProductUrlRef = useRef<string | null>(null)
  const sceneKeyRef = useRef<string>("")
  /** Consecutive silent scene recoveries — capped to avoid loops. */
  const sceneRecoveriesRef = useRef(0)
  /** Bumped after each successful scene rebuild — ZIP waits on this. */
  const sceneEpochRef = useRef(0)
  const scaleRef = useRef(scale)
  const zoomModeRef = useRef(zoomMode)
  useLayoutEffect(() => {
    scaleRef.current = scale
  }, [scale])
  useLayoutEffect(() => {
    zoomModeRef.current = zoomMode
  }, [zoomMode])
  const [ready, setReady] = useState(false)
  const [sceneError, setSceneError] = useState<string | null>(null)
  const [rebuildNonce, setRebuildNonce] = useState(0)
  /** Bumped after mount / scene rebuild to force CSS softbox paint immediately. */
  const [lightingPaintKey, setLightingPaintKey] = useState(0)

  const syncViewport = (): FabricViewportFrame | null => {
    const canvas = fabricRef.current
    const host = containerRef.current
    if (!isFabricCanvasAlive(canvas) || !host) return null
    const rect = host.getBoundingClientRect()
    const hostW = Math.floor(rect.width) || host.clientWidth
    const hostH = Math.floor(rect.height) || host.clientHeight
    if (hostW < 2 || hostH < 2) return null

    // Cap height by chrome: window - header - topToolbar - 40px.
    const { width: w, height: h } = resolveFitContainerSize(
      hostW,
      hostH,
      typeof window !== "undefined" ? window.innerHeight : undefined
    )

    // Keep Fabric backstore in sync with the parent box (never 0×0).
    canvas.setWidth(w)
    canvas.setHeight(h)

    const mode = zoomModeRef.current
    // Fit: min((availW - 80) / canvasW, (availH - 80) / canvasH) via padding=40.
    const zoom =
      mode === "fit"
        ? computeFitZoom(w, h, FABRIC_FIT_PADDING)
        : scaleRef.current

    const frame = applyFabricZoomView(canvas, {
      containerWidth: w,
      containerHeight: h,
      zoom,
      padding: FABRIC_FIT_PADDING,
    })
    setArtboardFrame(frame)
    return frame
  }

  useLayoutEffect(() => {
    syncViewportRef.current = syncViewport
  })

  const sceneKey = useMemo(
    () =>
      structureKey({
        layers,
        productPreviewUrl,
        backgroundPreviewUrl,
        generationEpoch,
      }),
    [layers, productPreviewUrl, backgroundPreviewUrl, generationEpoch]
  )

  const showBusyOverlay =
    busyKind === "generating" ||
    busyKind === "removing-bg" ||
    busyKind === "loading-image"

  useLayoutEffect(() => {
    ensureCustomProps()
    ensureFabricQualityDefaults()
    ensureFabricWebGL()
    const el = canvasRef.current
    if (!el) return

    // Reuse a live instance across React Strict Mode effect re-runs.
    // Never call canvas.dispose() here — async destroy() frees the drawing
    // context and races remounts (black void). Soft teardown uses clear().
    let canvas = fabricRef.current
    if (!isFabricCanvasAlive(canvas)) {
      const host = containerRef.current
      const rect = host?.getBoundingClientRect()
      const rawW = Math.max(
        1,
        Math.floor(rect?.width ?? 0) || host?.clientWidth || CANVAS_WIDTH
      )
      const rawH = Math.max(
        1,
        Math.floor(rect?.height ?? 0) || host?.clientHeight || CANVAS_HEIGHT
      )
      const { width: initW, height: initH } = resolveFitContainerSize(
        rawW,
        rawH,
        typeof window !== "undefined" ? window.innerHeight : undefined
      )
      canvas = new FabricCanvas(el, {
        width: initW,
        height: initH,
        preserveObjectStacking: true,
        selection: true,
        // Zinc gray — never pure black void while the scene is still loading.
        backgroundColor: "#18181b",
        stopContextMenu: true,
        controlsAboveOverlay: true,
        // Batch adds during rebuild; interactive frames call requestRenderAll.
        renderOnAddRemove: false,
        // Device-pixel buffer + smoothing — crisp badges/icons when scaled down.
        enableRetinaScaling: true,
        imageSmoothingEnabled: true,
        targetFindTolerance: 6,
        perPixelTargetFind: false,
      })
      // Explicit size from parent box — avoids 0×0 black screen on first paint.
      canvas.setWidth(initW)
      canvas.setHeight(initH)
      fabricRef.current = canvas
    } else {
      const host = containerRef.current
      const rect = host?.getBoundingClientRect()
      if (rect && rect.width >= 2 && rect.height >= 2) {
        const sized = resolveFitContainerSize(
          Math.floor(rect.width),
          Math.floor(rect.height),
          typeof window !== "undefined" ? window.innerHeight : undefined
        )
        canvas.setWidth(sized.width)
        canvas.setHeight(sized.height)
      }
      // Recover from soft-teardown / empty remount — gray until scene rebuild paints.
      if (canvas.getObjects().length === 0) {
        canvas.backgroundColor = "#18181b"
        canvas.requestRenderAll()
      }
    }
    sceneEpochRef.current = 0
    sceneKeyRef.current = ""
    fittedProductUrlRef.current = null
    setReady(true)
    setSceneError(null)
    // Strict Mode remount keeps ready=true after soft teardown — force scene rebuild
    // so product / layers are reattached instead of leaving a blank rectangle.
    setRebuildNonce((n) => n + 1)
    // Apply lighting from store immediately on canvas mount (not via slider onChange).
    applyLightingEffects(canvas, useEditorStore.getState().softbox)
    setLightingPaintKey((n) => n + 1)
    if (isFabricCanvasAlive(canvas)) {
      canvas.requestRenderAll()
    }

    // Initial Fit: size to wrapper, zoom so 1080×1440 fits with ~40px padding, center.
    // Host can be 0×0 for a frame (flex layout) — retry until real metrics exist.
    let fitRetries = 0
    let fitRaf = 0
    const applyInitialFit = () => {
      fitRaf = 0
      const frame = syncViewportRef.current()
      if (frame || fitRetries >= 60) return
      fitRetries += 1
      fitRaf = requestAnimationFrame(applyInitialFit)
    }
    applyInitialFit()
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            syncViewportRef.current()
          })
        : null
    if (ro && containerRef.current) {
      ro.observe(containerRef.current)
    }

    const lastGuideSigRef = { current: "" }
    let guideRaf = 0

    const scheduleGuides = (moving: EngineObject) => {
      if (guideRaf) cancelAnimationFrame(guideRaf)
      guideRaf = requestAnimationFrame(() => {
        guideRaf = 0
        applySmartSnap(canvas, moving, lastGuideSigRef)
      })
    }

    /** Commit transform to Zustand only when a gesture ends (60 FPS during drag). */
    const commitTransform = (obj: EngineObject | undefined) => {
      if (!obj) return
      // Nested chip IText fires object:modified on editing exit with LOCAL left/top
      // (near 0). Always persist the parent Group's canvas position instead.
      const transformTarget = (
        isChipTextPart(obj) ? (chipGroupOf(obj) as EngineObject | null) : obj
      ) as EngineObject | null
      if (!transformTarget?.layerId) return
      const patch = objectToLayerPatch(transformTarget)
      if (!patch) return
      writingStoreRef.current = true
      updateLayer(transformTarget.layerId, patch)
      queueMicrotask(() => {
        writingStoreRef.current = false
      })
    }

    const enterTextEditing = (text: IText) => {
      if (text.isEditing || text.selectable === false) return
      // Keep left/top origin while editing — center origin drifts the caret/selection.
      text.set({
        originX: "left",
        originY: "top",
        padding: 0,
        objectCaching: false,
      })
      const wired = text as IText & { __editCoordsWired?: boolean }
      if (!wired.__editCoordsWired) {
        wired.__editCoordsWired = true
        text.on("editing:entered", () => {
          canvas.calcOffset()
          text.setCoords()
        })
      }
      syncTextEditingCoords(canvas, text)
      canvas.setActiveObject(text)
      text.enterEditing()
      text.selectAll()
      // Re-sync after Fabric mounts the hidden textarea (layout can shift offset).
      syncTextEditingCoords(canvas, text)
      canvas.requestRenderAll()
    }

    /** Double-click path for nested chip Textbox inside an interactive Group. */
    const enterChipTextEditing = (text: IText) => {
      if (text.isEditing) return
      if ((text as IText & { editable?: boolean }).editable === false) return
      text.set({
        originX: "left",
        originY: "top",
        padding: 0,
        objectCaching: false,
      })
      const wired = text as IText & { __editCoordsWired?: boolean }
      if (!wired.__editCoordsWired) {
        wired.__editCoordsWired = true
        text.on("editing:entered", () => {
          canvas.calcOffset()
          text.setCoords()
        })
      }
      const group = chipGroupOf(text) as EngineObject | null
      if (group?.layerId) selectLayer(group.layerId)
      // Snapshot canvas position before edit/layout so exit can restore it.
      if (group) {
        group.__badgeAbsLeft = group.left ?? 0
        group.__badgeAbsTop = group.top ?? 0
      }
      syncTextEditingCoords(canvas, text)
      canvas.setActiveObject(text)
      text.enterEditing()
      text.selectAll()
      syncTextEditingCoords(canvas, text)
      canvas.requestRenderAll()
    }

    const selectChipLayer = (layer: CanvasLayer) => {
      if (!layer.chip) return
      clearChipInlineEditors(canvas)
      selectLayer(layer.id)
    }

    const resolveLayerId = (obj: EngineObject | undefined): string | null => {
      if (!obj || isSmartGuideObject(obj)) return null
      if (obj.layerId) return obj.layerId
      const group = chipGroupOf(obj) as EngineObject | null
      return group?.layerId ?? null
    }

    const onSelect = () => {
      const obj = canvas.getActiveObject() as EngineObject | undefined
      if (obj && isSmartGuideObject(obj)) return
      // Nested chip text still maps to the badge layer for the tools panel.
      selectLayer(resolveLayerId(obj))
    }
    const onSelectionCleared = () => selectLayer(null)

    // Mid-gesture: keep transforms in Fabric only — no Zustand / React updates.
    const onObjectMoving = (e: { target?: FabricObject }) => {
      clickEditRef.current.moved = true
      const target = e.target as EngineObject | undefined
      if (!target || isSmartGuideObject(target)) return
      // Soft canvas-bounds clamp (left/top only) before smart guides.
      constrainObjectToArtboard(target)
      scheduleGuides(target)
    }
    const onObjectScaling = (e: { target?: FabricObject }) => {
      clickEditRef.current.moved = true
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      const target = e.target as EngineObject | undefined
      if (target && !isSmartGuideObject(target)) {
        constrainScaleToArtboard(target)
      }
      canvas.requestRenderAll()
    }
    const onObjectRotating = () => {
      clickEditRef.current.moved = true
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      canvas.requestRenderAll()
    }

    const onMouseDown = (opt: { target?: FabricObject }) => {
      const target = opt.target as EngineObject | undefined
      if (!target?.layerId || isSmartGuideObject(target)) {
        clickEditRef.current = {
          layerId: null,
          wasAlreadySelected: false,
          moved: false,
        }
        return
      }
      const active = canvas.getActiveObject() as EngineObject | undefined
      clickEditRef.current = {
        layerId: target.layerId,
        wasAlreadySelected: active?.layerId === target.layerId,
        moved: false,
      }
      interactingRef.current = true
      beginHistoryTransaction()
    }

    const onObjectModified = (e: { target?: FabricObject }) => {
      const target = e.target as EngineObject | undefined
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      commitTransform(target)
      commitHistoryTransaction()
      interactingRef.current = false
      canvas.requestRenderAll()
    }

    const onMouseUp = (opt: { target?: FabricObject }) => {
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)

      const gesture = clickEditRef.current
      const target = opt.target as EngineObject | undefined

      // Click-to-edit: second click on an already-selected infographic (no drag).
      if (
        !gesture.moved &&
        gesture.wasAlreadySelected &&
        target?.layerId &&
        target.layerId === gesture.layerId &&
        target.layerRole === "infographic"
      ) {
        const layer = useEditorStore
          .getState()
          .layers.find((l) => l.id === target.layerId)
        if (layer && !layer.locked) {
          if (target.type === "i-text") {
            enterTextEditing(target as IText)
            interactingRef.current = false
            return
          }
          if (layer.chip) {
            // Second click on a badge: keep selection in the right tools panel.
            // Inline label edit is via double-click (enterEditing on nested IText).
            selectChipLayer(layer)
            interactingRef.current = false
            return
          }
        }
      }

      // Run after object:modified in the same gesture so history stays one step.
      queueMicrotask(() => {
        if (!interactingRef.current) return
        interactingRef.current = false
        commitHistoryTransaction()
      })
      canvas.requestRenderAll()
    }

    const onTextChanged = (e: { target?: FabricObject }) => {
      const obj = e.target as EngineObject | undefined
      if (!obj) return
      // Nested badge text: resize plate + re-anchor children as glyphs change.
      if (isChipTextPart(obj)) {
        const group = chipGroupOf(obj)
        if (group) updateBadgeLayout(group)
        if ((obj as Textbox).isEditing) {
          syncTextEditingCoords(canvas, obj as Textbox)
        }
        return
      }
      // Refresh selection/control bounds after glyph metrics change.
      obj.setCoords()
      canvas.requestRenderAll()
      if (!obj.layerId || obj.type !== "i-text") return
      // Overlay chip editors sync on editing:exited, not per keystroke.
      if (obj.isChipInlineEditor) return
      const text = (obj as IText).text ?? ""
      writingStoreRef.current = true
      updateLayer(obj.layerId, { text })
      queueMicrotask(() => {
        writingStoreRef.current = false
      })
    }

    // Dblclick: edit standalone text or nested chip Textbox in place.
    const onMouseDblClick = (opt: {
      target?: FabricObject
      subTargets?: FabricObject[]
    }) => {
      const direct = opt.target as EngineObject | undefined
      const fromSub = opt.subTargets?.find((t) =>
        isChipTextObjectType(t.type)
      ) as Textbox | undefined
      const textHit =
        isChipTextObjectType(direct?.type) ? (direct as Textbox) : fromSub ?? null

      if (textHit && isChipTextPart(textHit)) {
        const layerId = resolveLayerId(textHit as EngineObject)
        const layer = layerId
          ? useEditorStore.getState().layers.find((l) => l.id === layerId)
          : undefined
        if (!layer || layer.locked) return
        enterChipTextEditing(textHit)
        return
      }

      if (direct?.type === "i-text" && direct.layerRole === "infographic") {
        const layer = useEditorStore
          .getState()
          .layers.find((l) => l.id === direct.layerId)
        if (!layer || layer.locked) return
        enterTextEditing(direct as IText)
        return
      }

      if (!direct?.layerId || direct.layerRole !== "infographic") return
      const layer = useEditorStore
        .getState()
        .layers.find((l) => l.id === direct.layerId)
      if (!layer || layer.locked) return
      if (layer.chip) selectChipLayer(layer)
    }

    const onTextEditingEntered = (e: { target?: FabricObject }) => {
      const text = e.target
      if (!text || !isChipTextObjectType(text.type)) return
      syncTextEditingCoords(canvas, text as IText)
    }

    /** Persist chip label/subtitle into Zustand when leaving canvas edit mode. */
    const onTextEditingExited = (e: { target?: FabricObject }) => {
      const obj = e.target as EngineObject | undefined
      if (!isChipTextPart(obj)) return

      const part = obj.chipPart as "label" | "subtitle"
      const layerId = resolveLayerId(obj)
      if (!layerId) return
      const layer = useEditorStore.getState().layers.find((l) => l.id === layerId)
      if (!layer?.chip) return

      const nextText = (obj as Textbox).text ?? ""
      const nextChip: FeatureChipDraft =
        part === "label"
          ? { ...layer.chip, label: nextText }
          : { ...layer.chip, subtitle: nextText || undefined }

      const group = chipGroupOf(obj) as (Group & EngineObject) | null
      const absoluteLeft = group?.__badgeAbsLeft ?? group?.left ?? null
      const absoluteTop = group?.__badgeAbsTop ?? group?.top ?? null

      writingStoreRef.current = true
      updateLayer(layerId, {
        chip: nextChip,
        ...(part === "label"
          ? { name: `Плашка «${nextText || layer.chip.label}»` }
          : {}),
      })
      if (group) {
        applyChipContentInPlace(group, nextChip)
        // Re-apply saved canvas coords after layout / any detach-regroup path.
        if (absoluteLeft != null && absoluteTop != null) {
          group.set({ left: absoluteLeft, top: absoluteTop })
          group.setCoords()
        }
        delete group.__badgeAbsLeft
        delete group.__badgeAbsTop
      }
      queueMicrotask(() => {
        writingStoreRef.current = false
      })
      canvas.requestRenderAll()
    }

    canvas.on("selection:created", onSelect)
    canvas.on("selection:updated", onSelect)
    canvas.on("selection:cleared", onSelectionCleared)
    canvas.on("object:moving", onObjectMoving)
    canvas.on("object:scaling", onObjectScaling)
    canvas.on("object:rotating", onObjectRotating)
    canvas.on("mouse:down", onMouseDown)
    canvas.on("object:modified", onObjectModified)
    canvas.on("mouse:up", onMouseUp)
    canvas.on("text:changed", onTextChanged)
    canvas.on("mouse:dblclick", onMouseDblClick)
    canvas.on("text:editing:entered", onTextEditingEntered)
    canvas.on("text:editing:exited", onTextEditingExited)

    /** Delete/Backspace removes the selection unless IText is actively editing. */
    const onCanvasKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Backspace" && event.key !== "Delete") return

      const domTarget = event.target
      if (
        domTarget instanceof HTMLElement &&
        (domTarget.isContentEditable ||
          domTarget.tagName === "INPUT" ||
          domTarget.tagName === "TEXTAREA" ||
          domTarget.tagName === "SELECT")
      ) {
        return
      }

      const active = canvas.getActiveObject() as
        | (EngineObject & { isEditing?: boolean })
        | undefined
      if (!active) return
      // While editing text, let Backspace/Delete remove characters.
      if (active.isEditing === true) return
      if (isSmartGuideObject(active) || active.layerRole === "background") {
        return
      }

      event.preventDefault()
      event.stopPropagation()

      const targets = (canvas.getActiveObjects() as EngineObject[]).filter(
        (obj) =>
          !isSmartGuideObject(obj) &&
          obj.layerRole !== "background" &&
          (obj as IText).isEditing !== true
      )
      if (targets.length === 0) return

      // Nested chip text → delete the whole badge Group, not the child alone.
      const removeTargets: EngineObject[] = []
      const seen = new Set<EngineObject>()
      for (const obj of targets) {
        const group =
          isChipTextPart(obj) ? (chipGroupOf(obj) as EngineObject | null) : null
        const victim = group ?? obj
        if (seen.has(victim)) continue
        seen.add(victim)
        removeTargets.push(victim)
      }

      const layerIds = removeTargets
        .map((obj) => obj.layerId)
        .filter((id): id is string => Boolean(id))

      for (const obj of removeTargets) {
        canvas.remove(obj)
      }
      canvas.discardActiveObject()
      canvas.requestRenderAll()

      const { removeLayer } = useEditorStore.getState()
      for (const id of layerIds) {
        removeLayer(id)
      }
    }

    window.addEventListener("keydown", onCanvasKeyDown)

    registerFabricExporter({
      getCanvas: () => fabricRef.current,
      getSceneEpoch: () => sceneEpochRef.current,
      toPngDataUrl: async (size?: FabricExportSize) => {
        clearSmartGuides(canvas)
        // Live view hides Fabric softbox (CSS owns light) — reveal for raster export.
        return withFabricSoftboxVisibleForExport(canvas, () =>
          fabricCanvasToPngDataUrl(canvas, size ?? FABRIC_EXPORT_PRESETS[0])
        )
      },
      toPngBytes: async (size?: FabricExportSize) => {
        clearSmartGuides(canvas)
        return withFabricSoftboxVisibleForExport(canvas, () =>
          fabricCanvasToPngBytes(canvas, size ?? FABRIC_EXPORT_PRESETS[0])
        )
      },
    })

    return () => {
      window.removeEventListener("keydown", onCanvasKeyDown)
      if (guideRaf) cancelAnimationFrame(guideRaf)
      if (fitRaf) cancelAnimationFrame(fitRaf)
      ro?.disconnect()
      registerFabricExporter(null)
      clearSoftboxCaches()
      sceneEpochRef.current = 0
      try {
        clearChipInlineEditors(canvas)
        canvas.off("selection:created", onSelect)
        canvas.off("selection:updated", onSelect)
        canvas.off("selection:cleared", onSelectionCleared)
        canvas.off("object:moving", onObjectMoving)
        canvas.off("object:scaling", onObjectScaling)
        canvas.off("object:rotating", onObjectRotating)
        canvas.off("mouse:down", onMouseDown)
        canvas.off("object:modified", onObjectModified)
        canvas.off("mouse:up", onMouseUp)
        canvas.off("text:changed", onTextChanged)
        canvas.off("mouse:dblclick", onMouseDblClick)
        canvas.off("text:editing:entered", onTextEditingEntered)
        canvas.off("text:editing:exited", onTextEditingExited)
        // Soft teardown: keep Fabric instance + scene objects intact across
        // React Strict Mode effect re-runs. Never dispose() (kills 2d context)
        // and never clear() here — that left a black void because `ready` stayed
        // true and the scene rebuild effect did not re-fire.
        canvas.discardActiveObject()
        sceneKeyRef.current = ""
        fittedProductUrlRef.current = null
      } catch {
        // Ignore teardown races during navigation away from the editor.
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Display zoom via Fabric viewport (setZoom + absolutePan). Replaces cssOnly
  // sizing so hit-testing and transform handles stay aligned with the artboard.
  useLayoutEffect(() => {
    if (!ready) return
    syncViewportRef.current()
  }, [scale, zoomMode, ready])

  /**
   * Protected product bootstrap (Fabric v6 Promise fromURL).
   * Ensures that when a product image URL exists after mount, the bitmap is
   * loaded and painted — even if the full scene rebuild races Strict Mode.
   */
  useEffect(() => {
    if (!ready || !productPreviewUrl) return
    const canvas = fabricRef.current
    if (!isFabricCanvasAlive(canvas) || !canvasRef.current) return

    let cancelled = false

    const bootstrapProduct = async () => {
      try {
        const existing = findByLayerId(canvas, "layer_product")
        if (
          existing &&
          (existing instanceof FabricImage || existing.type === "image")
        ) {
          forceCanvasVisualSync(canvas)
          setLightingPaintKey((n) => n + 1)
          return
        }

        const img = await loadImage(productPreviewUrl)
        if (cancelled || !isFabricCanvasAlive(fabricRef.current)) return
        const live = fabricRef.current

        // Scene rebuild may have won the race — don't double-add.
        const again = findByLayerId(live, "layer_product")
        if (
          again &&
          (again instanceof FabricImage || again.type === "image")
        ) {
          forceCanvasVisualSync(live)
          setLightingPaintKey((n) => n + 1)
          return
        }

        const nw = Math.max(1, img.width || 1)
        const nh = Math.max(1, img.height || 1)
        const scale = Math.min(
          (CANVAS_WIDTH * 0.7) / nw,
          (CANVAS_HEIGHT * 0.7) / nh
        )

        // Empty canvas: paint gray studio + centered product (user-facing fix).
        if (live.getObjects().length === 0) {
          live.backgroundColor = "#18181b"
          img.set({
            left: CANVAS_WIDTH / 2,
            top: CANVAS_HEIGHT / 2,
            originX: "center",
            originY: "center",
            objectCaching: true,
          })
          img.scale(Math.max(0.001, scale))
          markObject(img, "layer_product", "product")
          live.add(img)
          live.setActiveObject(img)
          syncViewportRef.current()
          forceCanvasVisualSync(live)
          setLightingPaintKey((n) => n + 1)
          return
        }

        // Non-empty scene without a product image — force a full rebuild.
        sceneKeyRef.current = ""
        setRebuildNonce((n) => n + 1)
      } catch (err) {
        if (process.env.NODE_ENV !== "production") {
          console.error("[fabric-canvas] product bootstrap failed", err)
        }
      }
    }

    void bootstrapProduct()
    return () => {
      cancelled = true
    }
  }, [ready, productPreviewUrl])

  // Rebuild 3-layer scene when structure changes (not on pure transforms).
  // CRITICAL: do NOT depend on `layers` directly — syncLayerGeometry during product
  // fit used to cancel this effect mid-flight; sceneKeyRef was already stamped, so
  // the retry early-returned and badges never landed on Fabric (store-only ghost).
  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || !ready) return
    const buildKey = `${sceneKey}#${rebuildNonce}`
    const storeLayers = useEditorStore.getState().layers

    // Skip only when this key was FULLY committed AND every chip/text is on canvas.
    if (
      sceneKeyRef.current === buildKey &&
      canvas.getObjects().length > 0 &&
      storeLayers.length > 0 &&
      !canvasMissingInfographicLayers(canvas, storeLayers)
    ) {
      return
    }

    let cancelled = false
    const built: EngineObject[] = []

    const rebuild = async () => {
      // Always read fresh layers — geometry may change without a new sceneKey.
      const layersNow = useEditorStore.getState().layers
      const productUrl = useEditorStore.getState().productPreviewUrl
      const backgroundUrl = useEditorStore.getState().backgroundPreviewUrl
      /** Defer store writes until after Fabric commit so we never cancel ourselves. */
      let pendingProductFit: {
        id: string
        width: number
        height: number
        x: number
        y: number
      } | null = null

      try {
        if (layersNow.length === 0) {
          if (cancelled) return
          clearChipInlineEditors(canvas)
          canvas.renderOnAddRemove = false
          canvas.clear()
          // Gray studio — never a pure black void when the stack is empty.
          canvas.backgroundColor = "#18181b"
          canvas.discardActiveObject()

          // Keep product visible even before layers hydrate (UUID design load).
          if (productUrl) {
            try {
              const img = await loadImage(productUrl)
              if (cancelled || !isFabricCanvasAlive(fabricRef.current)) return
              const nw = Math.max(1, img.width || 1)
              const nh = Math.max(1, img.height || 1)
              const fit = Math.min(
                (CANVAS_WIDTH * 0.7) / nw,
                (CANVAS_HEIGHT * 0.7) / nh
              )
              img.set({
                left: CANVAS_WIDTH / 2,
                top: CANVAS_HEIGHT / 2,
                originX: "center",
                originY: "center",
                objectCaching: true,
              })
              img.scale(Math.max(0.001, fit))
              markObject(img, "layer_product", "product")
              canvas.add(img)
              canvas.setActiveObject(img)
            } catch {
              // Preview optional while layers are still empty.
            }
          }

          if (cancelled || !isFabricCanvasAlive(canvas)) return
          canvas.requestRenderAll()
          syncViewportRef.current()
          forceCanvasVisualSync(canvas)
          setLightingPaintKey((n) => n + 1)
          sceneEpochRef.current += 1
          sceneRecoveriesRef.current = 0
          setSceneError(null)
          // Stamp only after a finished empty-stack paint.
          sceneKeyRef.current = buildKey
          const busy = useEditorStore.getState().busyKind
          if (busy === "generating" || busy === "loading-image") {
            setBusyKind("idle")
          }
          return
        }

        const bg = await buildBackgroundLayer({
          softbox: useEditorStore.getState().softbox,
          backgroundPreviewUrl: backgroundUrl,
        })
        if (cancelled) {
          disposeBuiltObjects([bg])
          return
        }
        built.push(bg)

        const interactive = layersNow
          .filter((l) => l.visible && l.type !== "background")
          .sort((a, b) => a.zIndex - b.zIndex)

        const productLayers = interactive.filter(
          (l) => l.type === "image" || l.id === "layer_product"
        )
        const badgeAndTextLayers = interactive.filter(
          (l) =>
            !(l.type === "image" || l.id === "layer_product") &&
            (l.type === "text" || (l.type === "shape" && l.chip))
        )

        // 1) Product image MUST finish loading before badges/texts are built.
        for (const layer of productLayers) {
          if (cancelled) {
            disposeBuiltObjects(built)
            return
          }

          let buildLayer = layer
          if (productUrl && fittedProductUrlRef.current !== productUrl) {
            try {
              const probe = await loadImage(productUrl)
              if (cancelled) {
                disposeBuiltObjects(built)
                return
              }
              const fitted = fitProductPhotoToArtboard(
                probe.width || 1,
                probe.height || 1
              )
              fittedProductUrlRef.current = productUrl
              pendingProductFit = {
                id: layer.id,
                width: fitted.width,
                height: fitted.height,
                x: fitted.x,
                y: fitted.y,
              }
              // Use fitted geometry for this build without touching Zustand yet.
              buildLayer = {
                ...layer,
                width: fitted.width,
                height: fitted.height,
                x: fitted.x,
                y: fitted.y,
              }
              if (useEditorStore.getState().busyKind === "loading-image") {
                setBusyKind("idle")
              }
            } catch {
              if (useEditorStore.getState().busyKind === "loading-image") {
                setBusyKind("idle")
              }
            }
          } else {
            buildLayer =
              useEditorStore.getState().layers.find((l) => l.id === layer.id) ??
              layer
          }

          const product = await safeBuildLayer(buildLayer, (l) =>
            buildProductObject(l, productUrl)
          )
          if (cancelled) {
            if (product) disposeBuiltObjects([product])
            disposeBuiltObjects(built)
            return
          }
          if (product) built.push(product)
        }

        // 2) Badges/texts only after product bitmap is ready (+ fonts for chips).
        const hasBadges = badgeAndTextLayers.some(
          (l) => l.type === "shape" && l.chip
        )
        if (hasBadges) {
          await awaitDocumentFontsReady()
        }

        for (const layer of badgeAndTextLayers) {
          if (cancelled) {
            disposeBuiltObjects(built)
            return
          }

          if (layer.type === "text") {
            const text = await safeBuildLayer(layer, (l) => buildTextObject(l))
            if (cancelled) {
              if (text) disposeBuiltObjects([text])
              disposeBuiltObjects(built)
              return
            }
            if (text) built.push(text)
            continue
          }

          if (layer.type === "shape" && layer.chip) {
            const chip = await safeBuildLayer(layer, (l) => buildChipObject(l))
            if (cancelled) {
              if (chip) disposeBuiltObjects([chip])
              disposeBuiltObjects(built)
              return
            }
            if (chip) built.push(chip)
          }
        }

        if (cancelled) {
          disposeBuiltObjects(built)
          return
        }

        // Flush any in-progress chip overlay editor before wiping the scene.
        clearChipInlineEditors(canvas)

        const prevSelected = useEditorStore.getState().selectedLayerId
        canvas.renderOnAddRemove = false
        canvas.clear()
        // Fallback gray until objects paint (avoids a black flash mid-rebuild).
        canvas.backgroundColor = "#18181b"

        // Preserve z-order from the original interactive sort when committing.
        const byId = new Map(
          built.map((obj) => [(obj as EngineObject).layerId ?? "", obj])
        )
        const ordered: EngineObject[] = [bg]
        for (const layer of interactive) {
          const obj = byId.get(layer.id)
          if (obj) ordered.push(obj)
        }
        const commitList = ordered.filter(
          (obj, i, arr) => arr.indexOf(obj) === i
        )

        // Split commit: background/product/text first; badges ONLY after fonts+assets.
        const badgeCommitList: FabricObject[] = []
        const baseCommitList: FabricObject[] = []
        for (const obj of commitList) {
          if (isBadgeGroupObject(obj)) {
            badgeCommitList.push(obj)
          } else {
            baseCommitList.push(obj)
          }
        }

        for (const obj of baseCommitList) {
          canvas.add(obj)
          const role = (obj as EngineObject).layerRole
          if (role === "infographic") {
            obj.set({ dirty: true })
            obj.setCoords()
            bringEngineObjectToFront(canvas, obj)
          }
        }
        built.length = 0

        await commitBadgeGroupsToCanvas(canvas, badgeCommitList)
        if (cancelled || !isFabricCanvasAlive(canvas)) return

        const productObj =
          findByLayerId(canvas, "layer_product") ??
          canvas
            .getObjects()
            .find((o) => (o as EngineObject).layerRole === "product")

        if (productObj instanceof FabricImage || productObj?.type === "image") {
          productObj.setCoords()
        }

        if (prevSelected) {
          const match = findByLayerId(canvas, prevSelected)
          if (match?.selectable) canvas.setActiveObject(match)
          else if (productObj?.selectable) canvas.setActiveObject(productObj)
        } else if (productObj?.selectable) {
          canvas.setActiveObject(productObj)
        }
        canvas.backgroundColor = "rgba(0,0,0,0)"
        syncViewportRef.current()
        forceCanvasVisualSync(canvas)

        // Persist deferred product fit AFTER Fabric commit (safe for store→effect).
        if (pendingProductFit) {
          writingStoreRef.current = true
          syncLayerGeometry(pendingProductFit.id, {
            width: pendingProductFit.width,
            height: pendingProductFit.height,
            x: pendingProductFit.x,
            y: pendingProductFit.y,
          })
          queueMicrotask(() => {
            writingStoreRef.current = false
          })
        }

        // Stamp success only when chips from the store are actually on Fabric.
        const finalLayers = useEditorStore.getState().layers
        if (!canvasMissingInfographicLayers(canvas, finalLayers)) {
          sceneKeyRef.current = buildKey
        } else {
          // Incomplete commit — force another pass (capped via sceneRecoveriesRef).
          sceneKeyRef.current = ""
          if (sceneRecoveriesRef.current < 5) {
            sceneRecoveriesRef.current += 1
            setRebuildNonce((n) => n + 1)
          }
          return
        }

        setLightingPaintKey((n) => n + 1)
        sceneEpochRef.current += 1
        sceneRecoveriesRef.current = 0
        setSceneError(null)
        const busy = useEditorStore.getState().busyKind
        if (busy === "generating" || busy === "loading-image") {
          setBusyKind("idle")
        }
      } catch (err) {
        disposeBuiltObjects(built)
        if (cancelled) return
        if (process.env.NODE_ENV !== "production") {
          console.error("[fabric-canvas] scene rebuild failed", err)
        }
        sceneKeyRef.current = ""
        if (sceneRecoveriesRef.current >= 3) {
          setSceneError(
            err instanceof Error
              ? err.message
              : "Не удалось собрать сцену холста"
          )
          return
        }
        sceneRecoveriesRef.current += 1
        recoverCanvasAfterRenderError(
          useEditorStore.getState().selectedLayerId
        )
        if (!cancelled) {
          setSceneError(null)
          setRebuildNonce((n) => n + 1)
        }
      }
    }

    void rebuild()
    return () => {
      cancelled = true
      // Do not dispose `built` here — rebuild may be mid-commit onto the live
      // canvas. Orphan pre-commit objects are disposed on cancelled checks above.
    }
  }, [
    ready,
    sceneKey,
    rebuildNonce,
    productPreviewUrl,
    backgroundPreviewUrl,
    syncLayerGeometry,
    setBusyKind,
  ])

  // Self-heal: store has chips but Fabric lost them (race / cancelled hydrate).
  // Debounced so it does not fight an in-flight rebuild from the same tick.
  useEffect(() => {
    if (!ready) return
    const timer = window.setTimeout(() => {
      const canvas = fabricRef.current
      if (!isFabricCanvasAlive(canvas)) return
      if (layers.length === 0) return
      if (!canvasMissingInfographicLayers(canvas, layers)) {
        sceneRecoveriesRef.current = 0
        return
      }
      if (sceneRecoveriesRef.current >= 5) return
      sceneRecoveriesRef.current += 1
      if (process.env.NODE_ENV !== "production") {
        console.warn(
          "[fabric-canvas] chips missing on canvas — forcing scene rebuild"
        )
      }
      sceneKeyRef.current = ""
      setRebuildNonce((n) => n + 1)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [ready, layers, sceneKey])

  // Softbox: CSS SoftboxLightOverlay is the live light. Debounced Fabric paint
  // keeps the hidden bitmap export-ready — no visual mode switch on slider commit.
  // Runs immediately on mount/ready from store softbox — never waits for slider onChange.
  useEffect(() => {
    if (!ready) return

    let debounceTimer = 0
    let raf = 0

    const runApply = () => {
      raf = 0
      try {
        const canvas = fabricRef.current
        if (!isFabricCanvasAlive(canvas)) return
        applyLightingEffects(canvas, useEditorStore.getState().softbox)
      } catch (err) {
        if (process.env.NODE_ENV !== "production") {
          console.error("[fabric-canvas] softbox apply failed", err)
        }
      }
    }

    const schedule = (immediate: boolean) => {
      window.clearTimeout(debounceTimer)
      if (raf) {
        cancelAnimationFrame(raf)
        raf = 0
      }
      if (immediate) {
        // Synchronously apply current lighting, then rAF for a second paint.
        runApply()
        raf = requestAnimationFrame(runApply)
        return
      }
      debounceTimer = window.setTimeout(() => {
        debounceTimer = 0
        raf = requestAnimationFrame(runApply)
      }, SOFTBOX_UPDATE_MS)
    }

    schedule(true)

    const unsub = useEditorStore.subscribe((state, prev) => {
      if (
        state.softbox === prev.softbox &&
        state.backgroundPreviewUrl === prev.backgroundPreviewUrl
      ) {
        return
      }
      schedule(false)
    })

    return () => {
      unsub()
      window.clearTimeout(debounceTimer)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [ready, lightingPaintKey])

  // Undo / external transform patches → Fabric objects (in-place, no Group rebuild)
  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || writingStoreRef.current || interactingRef.current) return
    // Color-picker scrub paints Fabric directly — don't fight it with a full layers pass.
    if (isChipAppearanceScrubbing()) return

    for (const layer of layers) {
      if (!layer.visible || layer.type === "background") continue
      const obj = findByLayerId(canvas, layer.id)
      if (!obj) continue
      if (obj.type === "i-text" && (obj as IText).isEditing) continue
      applyTransformFromLayer(obj, layer)
      if (layer.type === "text" && obj.type === "i-text") {
        const text = obj as IText
        if (text.text !== (layer.text ?? "")) {
          text.set("text", layer.text ?? "")
        }
        applyTextStyle(text, layer.textStyle)
      }
      // Badge: mutate existing Group children — never rebuild on label/subtitle keystrokes.
      if (
        layer.type === "shape" &&
        layer.chip &&
        (obj.type === "group" || obj instanceof Group)
      ) {
        const group = obj as Group
        const editingChild = group
          .getObjects()
          .some(
            (child) =>
              isChipTextObjectType(child.type) && (child as Textbox).isEditing
          )
        if (!editingChild) {
          applyChipContentInPlace(group, layer.chip)
          applyChipLiveColors(layer.id, layer.chip, { immediate: true })
        }
      }
    }
    canvas.requestRenderAll()
  }, [layers])

  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || interactingRef.current) return
    if (!selectedLayerId) {
      canvas.discardActiveObject()
      canvas.requestRenderAll()
      return
    }
    const match = findByLayerId(canvas, selectedLayerId)
    const active = canvas.getActiveObject() as EngineObject | undefined
    // Nested chip Textbox is a valid selection for the badge layer — don't steal it.
    if (
      active &&
      isChipTextPart(active) &&
      (active.layerId === selectedLayerId ||
        (chipGroupOf(active) as EngineObject | null)?.layerId === selectedLayerId)
    ) {
      return
    }
    if (match?.selectable && canvas.getActiveObject() !== match) {
      canvas.setActiveObject(match)
      canvas.requestRenderAll()
    }
  }, [selectedLayerId])

  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || !flashLayerId) return
    const match = findByLayerId(canvas, flashLayerId)
    if (!match) return
    const prev = match.opacity ?? 1
    match.set("opacity", Math.min(1, prev * 0.55 + 0.45))
    canvas.requestRenderAll()
    const t = window.setTimeout(() => {
      if (!isFabricCanvasAlive(fabricRef.current)) return
      match.set("opacity", prev)
      fabricRef.current?.requestRenderAll()
    }, 450)
    return () => window.clearTimeout(t)
  }, [flashLayerId])

  return (
    <div
      className={cn(
        "relative flex h-[calc(100vh-120px)] min-h-[500px] w-full items-center justify-center overflow-hidden bg-zinc-900 p-6"
      )}
    >
      <div
        ref={containerRef}
        id="editor-export-canvas"
        data-export-canvas="true"
        data-fabric-engine="true"
        className="relative h-full min-h-[500px] w-full overflow-hidden"
        role="img"
        aria-label={`Холст ${CANVAS_WIDTH}×${CANVAS_HEIGHT}`}
        aria-busy={showBusyOverlay}
      >
        {artboardFrame ? (
          <div
            aria-hidden
            className="pointer-events-none absolute z-0 bg-loft shadow-[0_24px_80px_rgba(0,0,0,0.55)] ring-1 ring-white/10"
            style={{
              left: artboardFrame.left,
              top: artboardFrame.top,
              width: artboardFrame.width,
              height: artboardFrame.height,
            }}
          />
        ) : null}

        <div className="absolute inset-0">
          {/* Softbox CSS light — always mounted; props update from softbox state. */}
          <SoftboxLightOverlay frame={artboardFrame} paintKey={lightingPaintKey} />
          <canvas ref={canvasRef} className="relative z-[1]" />
        </div>

        {sceneError ? (
          <div
            className="absolute inset-0 z-[140] flex flex-col items-center justify-center gap-3 bg-loft/90 px-4 text-center"
            role="alert"
            data-export-chrome="true"
          >
            <p className="font-heading text-sm font-semibold">Слой не загрузился</p>
            <p className="max-w-xs text-xs text-muted-foreground">{sceneError}</p>
            <button
              type="button"
              className="rounded-md border border-white/15 bg-white/5 px-3 py-1.5 text-xs hover:bg-white/10"
              onClick={() => {
                setSceneError(null)
                setRebuildNonce((n) => n + 1)
              }}
            >
              Пересобрать холст
            </button>
          </div>
        ) : null}

        {showBusyOverlay ? (
          <GenerationBusyOverlay
            kind={busyKind}
            progress={busyKind === "generating" ? busyProgress : null}
          />
        ) : null}
      </div>
    </div>
  )
}

/** Stable host — parent softbox saves must not remount Fabric / canvas DOM. */
const EditorFabricCanvas = memo(EditorFabricCanvasImpl)

export { EditorFabricCanvas }
