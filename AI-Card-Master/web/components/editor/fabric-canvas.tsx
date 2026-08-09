"use client"

import {
  Canvas as FabricCanvas,
  FabricImage,
  FabricObject,
  Group,
  IText,
  Line,
  Rect,
  Shadow,
  config as fabricConfig,
  initFilterBackend,
  util,
  type FabricObjectProps,
} from "fabric"
import {
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
} from "@/lib/editor/softbox"
import {
  useEditorStore,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import type { CanvasLayer, TextLayerStyle } from "@/types/canvas"
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

function ensureCustomProps(): void {
  const keys = [
    "layerId",
    "layerRole",
    "isSmartGuide",
    "isSoftbox",
    "chipPart",
    "isChipInlineEditor",
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

async function loadImage(url: string): Promise<FabricImage> {
  const isLocal =
    url.startsWith("data:") ||
    url.startsWith("blob:") ||
    url.startsWith("/")
  if (isLocal) {
    return FabricImage.fromURL(url)
  }
  try {
    return await FabricImage.fromURL(url, { crossOrigin: "anonymous" })
  } catch {
    return FabricImage.fromURL(url)
  }
}

/** Structural fingerprint — excludes transforms AND softbox (softbox updates in-place). */
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
    layers: args.layers.map((l) => ({
      id: l.id,
      type: l.type,
      visible: l.visible,
      locked: l.locked,
      zIndex: l.zIndex,
      opacity: l.opacity,
      text: l.text,
      textStyle: l.textStyle,
      chip: l.chip,
    })),
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

function isFabricCanvasAlive(canvas: FabricCanvas | null | undefined): boolean {
  if (!canvas || canvas.disposed || canvas.destroyed) return false
  try {
    const ctx = canvas.getContext()
    return Boolean(ctx)
  } catch {
    return false
  }
}

/**
 * Update softbox wash in-place on the existing Fabric.Image element.
 * Never recreates layers / never setElement on slider ticks (avoids canvas resize races).
 * Lost light object / dead canvas → quiet return (must not trip Error Boundary).
 */
function applySoftboxToFabric(
  canvas: FabricCanvas,
  softbox: SoftboxSettings,
  options: { preview: boolean; hideSoftboxForCssOverlay: boolean }
): void {
  try {
    if (!isFabricCanvasAlive(canvas)) return

    const img = findSoftboxImage(canvas)
    if (!img) return
    const bg = findBackgroundGroup(canvas)

    const caching = !options.preview && !options.hideSoftboxForCssOverlay
    const hide = options.hideSoftboxForCssOverlay

    // While CSS overlay is active, hide Fabric softbox once — skip paint + redundant renders.
    if (hide) {
      if ((img.opacity ?? 1) !== 0 || canvas.backgroundColor !== "rgba(0,0,0,0)") {
        img.set({ objectCaching: false, opacity: 0 })
        bg?.set({ objectCaching: false })
        canvas.backgroundColor = "rgba(0,0,0,0)"
        img.setCoords()
        bg?.setCoords()
        if (isFabricCanvasAlive(canvas)) canvas.requestRenderAll()
      }
      return
    }

    img.set({
      objectCaching: caching,
      opacity: 1,
    })
    bg?.set({ objectCaching: caching })

    const el = img.getElement()
    if (!(el instanceof HTMLCanvasElement)) return
    // Keep Fabric-bound size stable — do not resize for preview (clears buffer mid-render).
    if (el.width !== CANVAS_WIDTH || el.height !== CANVAS_HEIGHT) {
      el.width = CANVAS_WIDTH
      el.height = CANVAS_HEIGHT
    }
    if (!paintSoftboxInPlace(el, softbox)) return

    img.set({ dirty: true })
    img.setCoords()
    bg?.set({ dirty: true })
    bg?.setCoords()
    canvas.backgroundColor = "#0d0f12"
    if (isFabricCanvasAlive(canvas)) canvas.requestRenderAll()
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[fabric-canvas] softbox redraw failed", err)
    }
  }
}

/** Cheap CSS softbox preview — re-renders alone; does not remount Fabric. */
function SoftboxScrubOverlay() {
  const softboxScrubbing = useEditorStore((s) => s.softboxScrubbing)
  const softboxLivePreview = useEditorStore((s) => s.softboxLivePreview)
  const softbox = useEditorStore((s) => s.softbox)
  const backgroundPreviewUrl = useEditorStore((s) => s.backgroundPreviewUrl)

  if (!softboxScrubbing) return null

  const preview = softboxLivePreview ?? softbox
  let washStyle: CSSProperties | null = null
  let blendStyle: CSSProperties | null = null
  try {
    // Full wash under canvas only when Fabric softbox is the visible bg.
    if (!backgroundPreviewUrl) {
      washStyle = softboxOverlayStyle(preview)
    }
    blendStyle = softboxLightBlendStyle(preview)
  } catch {
    return null
  }

  return (
    <>
      {washStyle ? (
        <div
          aria-hidden
          data-export-chrome="true"
          className="pointer-events-none absolute inset-0 z-0"
          style={washStyle}
        />
      ) : null}
      {blendStyle ? (
        <div
          aria-hidden
          data-export-chrome="true"
          className="pointer-events-none absolute inset-0 z-[2]"
          style={blendStyle}
        />
      ) : null}
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
  const boxW = pctToPx(defs.width ?? 36.68, CANVAS_WIDTH)
  const boxH = pctToPx(defs.height ?? 64, CANVAS_HEIGHT)
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
    const img = await loadImage(productPreviewUrl)
    const nw = Math.max(1, img.width ?? 1)
    const nh = Math.max(1, img.height ?? 1)
    img.set({
      ...common,
      scaleX: (boxW / nw) * defs.scale,
      scaleY: (boxH / nh) * defs.scale,
    })
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
    // Cache when idle; Fabric disables cache while editing.
    objectCaching: true,
  })
  applyTextStyle(text, layer.textStyle)
  return markObject(text, layer.id, "infographic") as IText
}

async function buildChipObject(layer: CanvasLayer): Promise<Group> {
  const chip = layer.chip!
  const defs = layerDefaults(layer)
  const isGlass = chip.variant === "glass"
  const fg =
    chip.textColor ??
    (isGlass || (chip.blur ?? 0) > 0
      ? "#FFFFFF"
      : chipTextColor(chip.bgColor))

  const padX = isGlass ? 18 : 14
  const padY = isGlass ? 14 : 10
  const iconSize = isGlass ? 22 : 18
  const labelSize = isGlass ? 18 : 16
  const gap = 10

  const icon = await loadImage(chipIconDataUrl(chip.iconId, fg, 64))
  icon.set({
    originX: "left",
    originY: "center",
    left: padX,
    top: 0,
    selectable: false,
    evented: false,
  })
  icon.scaleToWidth(iconSize)
  ;(icon as EngineObject).chipPart = "icon"

  const chipFont = resolveFabricFontFamily("Inter")
  const label = new IText(chip.label, {
    left: padX + iconSize + gap,
    top: chip.subtitle ? -labelSize * 0.35 : 0,
    originX: "left",
    originY: "center",
    fontFamily: chipFont,
    fontSize: labelSize,
    fontWeight: "600",
    fill: fg,
    selectable: false,
    evented: false,
    // Never enterEditing inside a Group — Fabric miscomputes the text
    // transform matrix (origin/scale). Inline edit uses a detached IText.
    editable: false,
  })
  ;(label as EngineObject).chipPart = "label"

  const subtitle = chip.subtitle
    ? new IText(chip.subtitle, {
        left: padX + iconSize + gap,
        top: labelSize * 0.55,
        originX: "left",
        originY: "center",
        fontFamily: chipFont,
        fontSize: Math.max(11, labelSize * 0.72),
        fontWeight: "400",
        fill: fg,
        opacity: 0.7,
        selectable: false,
        evented: false,
        editable: false,
      })
    : null
  if (subtitle) (subtitle as EngineObject).chipPart = "subtitle"

  await Promise.resolve()
  const contentW = Math.max(label.width ?? 80, subtitle?.width ?? 0)
  const boxW = padX + iconSize + gap + contentW + padX
  const boxH = (chip.subtitle ? labelSize * 2.2 : labelSize) + padY * 2

  const bg = new Rect({
    left: 0,
    top: -boxH / 2,
    width: boxW,
    height: boxH,
    rx: chip.borderRadius,
    ry: chip.borderRadius,
    fill: chip.bgColor,
    stroke: isGlass ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.1)",
    strokeWidth: 1,
    selectable: false,
    evented: false,
  })
  ;(bg as EngineObject).chipPart = "bg"

  const children: FabricObject[] = [bg, icon, label]
  if (subtitle) children.push(subtitle)

  const group = new Group(children, {
    left: pctToPx(defs.x, CANVAS_WIDTH),
    top: pctToPx(defs.y, CANVAS_HEIGHT),
    originX: "left",
    originY: "top",
    scaleX: defs.scale,
    scaleY: defs.scale,
    angle: defs.rotation,
    opacity: layer.opacity,
    selectable: !layer.locked,
    evented: !layer.locked,
    hasControls: true,
    lockScalingFlip: true,
    subTargetCheck: false,
    objectCaching: true,
  })
  return markObject(group, layer.id, "infographic") as Group
}

/** Locate the editable chip label IText inside a badge Group. */
function findChipLabel(group: Group): IText | null {
  const tagged = group
    .getObjects()
    .find((o) => (o as EngineObject).chipPart === "label")
  if (tagged && tagged.type === "i-text") return tagged as IText

  // Fallback: first IText child is the label (subtitle is second).
  const texts = group.getObjects().filter((o) => o.type === "i-text")
  return (texts[0] as IText | undefined) ?? null
}

/**
 * World-space pose of an object (including parent Group scale/angle/origin).
 * Used to spawn a detached IText that lines up with the in-group glyph.
 */
function worldPoseFromObject(obj: FabricObject) {
  const decomposed = util.qrDecompose(obj.calcTransformMatrix())
  return {
    left: decomposed.translateX,
    top: decomposed.translateY,
    scaleX: decomposed.scaleX,
    scaleY: decomposed.scaleY,
    angle: decomposed.angle,
    skewX: decomposed.skewX,
    skewY: decomposed.skewY,
  }
}

function clearChipInlineEditors(canvas: FabricCanvas) {
  for (const obj of [...canvas.getObjects()]) {
    const engine = obj as EngineObject
    if (!engine.isChipInlineEditor) continue
    if (obj.type === "i-text" && (obj as IText).isEditing) {
      // Fires editing:exited → finish() persists label + removes editor.
      ;(obj as IText).exitEditing()
    }
    if (canvas.getObjects().includes(obj)) {
      canvas.remove(obj)
    }
  }
}

function objectToLayerPatch(obj: EngineObject): Partial<CanvasLayer> | null {
  if (!obj.layerId || obj.layerRole === "background") return null

  const scaleAvg = ((obj.scaleX ?? 1) + (obj.scaleY ?? 1)) / 2
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

  obj.set({
    left: pctToPx(defs.x, CANVAS_WIDTH),
    top: pctToPx(defs.y, CANVAS_HEIGHT),
    angle: defs.rotation,
    scaleX: defs.scale,
    scaleY: defs.scale,
    opacity: layer.opacity,
  })
}

function EditorFabricCanvas({ scale }: { scale: number }) {
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

  const canvasElRef = useRef<HTMLCanvasElement>(null)
  const fabricRef = useRef<FabricCanvas | null>(null)
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
  useLayoutEffect(() => {
    scaleRef.current = scale
  }, [scale])
  const [ready, setReady] = useState(false)
  const [sceneError, setSceneError] = useState<string | null>(null)
  const [rebuildNonce, setRebuildNonce] = useState(0)

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
    ensureFabricWebGL()
    const el = canvasElRef.current
    if (!el) return

    const canvas = new FabricCanvas(el, {
      width: CANVAS_WIDTH,
      height: CANVAS_HEIGHT,
      preserveObjectStacking: true,
      selection: true,
      backgroundColor: "#0d0f12",
      stopContextMenu: true,
      controlsAboveOverlay: true,
      // Batch adds during rebuild; interactive frames call requestRenderAll.
      renderOnAddRemove: false,
      // 1080×1440 @dpr2 ≈ 6M px — skip retina buffer for 60 FPS editing.
      enableRetinaScaling: false,
      targetFindTolerance: 6,
      perPixelTargetFind: false,
    })
    fabricRef.current = canvas
    sceneEpochRef.current = 0
    setReady(true)
    setSceneError(null)
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
      if (!obj?.layerId) return
      const patch = objectToLayerPatch(obj)
      if (!patch) return
      writingStoreRef.current = true
      updateLayer(obj.layerId, patch)
      queueMicrotask(() => {
        writingStoreRef.current = false
      })
    }

    const enterTextEditing = (text: IText) => {
      if (text.isEditing || text.selectable === false) return
      canvas.setActiveObject(text)
      text.enterEditing()
      text.selectAll()
      canvas.requestRenderAll()
    }

    /**
     * Chip badges stay as Groups (bg + icon + label [+ subtitle]). Fabric's
     * enterEditing on a nested IText miscomputes the transform when the group
     * has scale/origin changes — caret and selection drift. Instead: hide the
     * in-group label, spawn a top-level IText at the label's world matrix
     * (calcTransformMatrix → qrDecompose), sync text on editing:exited.
     */
    const startChipInlineEdit = (target: EngineObject, layer: CanvasLayer) => {
      if (!layer.chip) return
      const group =
        target instanceof Group || target.type === "group"
          ? (target as Group)
          : null
      if (!group) return

      clearChipInlineEditors(canvas)

      const label = findChipLabel(group)
      if (!label) return

      const pose = worldPoseFromObject(label)
      const prevVisible = label.visible !== false
      const prevCaching = group.objectCaching !== false

      // Hide nested glyphs so they don't stack under the floating editor.
      label.set({ visible: false })
      group.set({ objectCaching: false })
      group.dirty = true

      const editor = new IText(label.text ?? layer.chip.label, {
        left: pose.left,
        top: pose.top,
        originX: label.originX,
        originY: label.originY,
        scaleX: pose.scaleX,
        scaleY: pose.scaleY,
        angle: pose.angle,
        skewX: pose.skewX,
        skewY: pose.skewY,
        fontFamily: label.fontFamily,
        fontSize: label.fontSize,
        fontWeight: label.fontWeight,
        fill: label.fill,
        editable: true,
        selectable: true,
        evented: true,
        excludeFromExport: true,
        objectCaching: false,
      })
      ;(editor as EngineObject).isChipInlineEditor = true

      canvas.add(editor)
      canvas.bringObjectToFront(editor)
      canvas.setActiveObject(editor)
      editor.enterEditing()
      editor.selectAll()
      canvas.requestRenderAll()

      let settled = false
      const finish = () => {
        if (settled) return
        settled = true

        const next = editor.text?.trim() || layer.chip!.label

        // Restore nested label immediately (scene rebuild follows via store).
        try {
          label.set({ text: next, visible: prevVisible })
          group.set({ objectCaching: prevCaching })
          group.dirty = true
        } catch {
          // Group may already be disposed by a concurrent rebuild.
        }

        writingStoreRef.current = true
        beginHistoryTransaction()
        updateLayer(layer.id, { chip: { ...layer.chip!, label: next } })
        commitHistoryTransaction()

        editor.off("editing:exited", finish)
        try {
          canvas.remove(editor)
        } catch {
          // already removed
        }

        const restored = findByLayerId(canvas, layer.id)
        if (restored) canvas.setActiveObject(restored)

        canvas.requestRenderAll()
        queueMicrotask(() => {
          writingStoreRef.current = false
        })
      }
      editor.on("editing:exited", finish)
    }

    const onSelect = () => {
      const obj = canvas.getActiveObject() as EngineObject | undefined
      if (obj && isSmartGuideObject(obj)) return
      selectLayer(obj?.layerId ?? null)
    }

    canvas.on("selection:created", onSelect)
    canvas.on("selection:updated", onSelect)
    canvas.on("selection:cleared", () => selectLayer(null))

    // Mid-gesture: keep transforms in Fabric only — no Zustand / React updates.
    canvas.on("object:moving", (e) => {
      clickEditRef.current.moved = true
      const target = e.target as EngineObject | undefined
      if (!target || isSmartGuideObject(target)) return
      scheduleGuides(target)
    })
    canvas.on("object:scaling", () => {
      clickEditRef.current.moved = true
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      canvas.requestRenderAll()
    })
    canvas.on("object:rotating", () => {
      clickEditRef.current.moved = true
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      canvas.requestRenderAll()
    })

    canvas.on("mouse:down", (opt) => {
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
    })

    canvas.on("object:modified", (e) => {
      const target = e.target as EngineObject | undefined
      lastGuideSigRef.current = ""
      clearSmartGuides(canvas)
      commitTransform(target)
      commitHistoryTransaction()
      interactingRef.current = false
      canvas.requestRenderAll()
    })

    canvas.on("mouse:up", (opt) => {
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
            startChipInlineEdit(target, layer)
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
    })

    canvas.on("text:changed", (e) => {
      const obj = e.target as EngineObject | undefined
      if (!obj?.layerId || obj.type !== "i-text") return
      const text = (obj as IText).text ?? ""
      writingStoreRef.current = true
      updateLayer(obj.layerId, { text })
      queueMicrotask(() => {
        writingStoreRef.current = false
      })
    })

    // Keep dblclick as a fast path for first-time edit.
    canvas.on("mouse:dblclick", (opt) => {
      const target = opt.target as EngineObject | undefined
      if (!target?.layerId || target.layerRole !== "infographic") return
      const layer = useEditorStore
        .getState()
        .layers.find((l) => l.id === target.layerId)
      if (!layer || layer.locked) return

      if (target.type === "i-text") {
        enterTextEditing(target as IText)
        return
      }
      if (layer.chip) startChipInlineEdit(target, layer)
    })

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

      const layerIds = targets
        .map((obj) => obj.layerId)
        .filter((id): id is string => Boolean(id))

      for (const obj of targets) {
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
        return fabricCanvasToPngDataUrl(canvas, size ?? FABRIC_EXPORT_PRESETS[0])
      },
      toPngBytes: async (size?: FabricExportSize) => {
        clearSmartGuides(canvas)
        return fabricCanvasToPngBytes(canvas, size ?? FABRIC_EXPORT_PRESETS[0])
      },
    })

    return () => {
      window.removeEventListener("keydown", onCanvasKeyDown)
      if (guideRaf) cancelAnimationFrame(guideRaf)
      registerFabricExporter(null)
      try {
        canvas.dispose()
      } catch {
        // Ignore dispose races during hard navigation away from the editor.
      }
      fabricRef.current = null
      sceneEpochRef.current = 0
      setReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Display zoom via Fabric cssOnly — preserves hit-testing (CSS transform breaks it).
  useLayoutEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || !ready) return
    canvas.setDimensions(
      {
        width: `${CANVAS_WIDTH * scale}px`,
        height: `${CANVAS_HEIGHT * scale}px`,
      },
      { cssOnly: true }
    )
    canvas.calcOffset()
    canvas.requestRenderAll()
  }, [scale, ready])

  // Rebuild 3-layer scene when structure changes (not on pure transforms)
  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || !ready) return
    const buildKey = `${sceneKey}#${rebuildNonce}`
    // Empty layer stack must still clear leftover Fabric objects.
    if (
      sceneKeyRef.current === buildKey &&
      canvas.getObjects().length > 0 &&
      layers.length > 0
    ) {
      return
    }
    sceneKeyRef.current = buildKey

    let cancelled = false

    const rebuild = async () => {
      try {
        if (layers.length === 0) {
          if (cancelled) return
          clearChipInlineEditors(canvas)
          canvas.renderOnAddRemove = false
          canvas.clear()
          canvas.backgroundColor = "transparent"
          canvas.discardActiveObject()
          canvas.requestRenderAll()
          const z = scaleRef.current
          canvas.setDimensions(
            {
              width: `${CANVAS_WIDTH * z}px`,
              height: `${CANVAS_HEIGHT * z}px`,
            },
            { cssOnly: true }
          )
          canvas.calcOffset()
          sceneEpochRef.current += 1
          sceneRecoveriesRef.current = 0
          setSceneError(null)
          const busy = useEditorStore.getState().busyKind
          if (busy === "generating" || busy === "loading-image") {
            setBusyKind("idle")
          }
          return
        }

        const bg = await buildBackgroundLayer({
          softbox: useEditorStore.getState().softbox,
          backgroundPreviewUrl,
        })
        if (cancelled) return

        const interactive = layers
          .filter((l) => l.visible && l.type !== "background")
          .sort((a, b) => a.zIndex - b.zIndex)

        const built: EngineObject[] = [bg]

        for (const layer of interactive) {
          if (cancelled) return

          if (layer.type === "image" || layer.id === "layer_product") {
            if (
              productPreviewUrl &&
              fittedProductUrlRef.current !== productPreviewUrl
            ) {
              try {
                const probe = await loadImage(productPreviewUrl)
                const fitted = fitImageLayerBox(
                  probe.width || 1,
                  probe.height || 1,
                  52,
                  64
                )
                const d = layerDefaults(layer)
                const cx = d.x + (d.width ?? fitted.width) / 2
                const cy = d.y + (d.height ?? fitted.height) / 2
                const next = clampLayerPosition(
                  cx - fitted.width / 2,
                  cy - fitted.height / 2,
                  fitted.width * d.scale,
                  fitted.height * d.scale
                )
                fittedProductUrlRef.current = productPreviewUrl
                writingStoreRef.current = true
                syncLayerGeometry(layer.id, {
                  width: fitted.width,
                  height: fitted.height,
                  x: next.x,
                  y: next.y,
                })
                queueMicrotask(() => {
                  writingStoreRef.current = false
                })
                if (useEditorStore.getState().busyKind === "loading-image") {
                  setBusyKind("idle")
                }
              } catch {
                if (useEditorStore.getState().busyKind === "loading-image") {
                  setBusyKind("idle")
                }
              }
            }

            const latest =
              useEditorStore.getState().layers.find((l) => l.id === layer.id) ??
              layer
            const product = await safeBuildLayer(latest, (l) =>
              buildProductObject(l, productPreviewUrl)
            )
            if (product) built.push(product)
            continue
          }

          if (layer.type === "text") {
            const text = await safeBuildLayer(layer, (l) => buildTextObject(l))
            if (text) built.push(text)
            continue
          }

          if (layer.type === "shape" && layer.chip) {
            const chip = await safeBuildLayer(layer, (l) => buildChipObject(l))
            if (chip) built.push(chip)
          }
        }

        if (cancelled) return

        // Flush any in-progress chip overlay editor before wiping the scene.
        clearChipInlineEditors(canvas)

        const prevSelected = useEditorStore.getState().selectedLayerId
        canvas.renderOnAddRemove = false
        canvas.clear()
        canvas.backgroundColor = "#0d0f12"
        for (const obj of built) canvas.add(obj)
        // Keep false — interactive frames call requestRenderAll explicitly.

        if (prevSelected) {
          const match = findByLayerId(canvas, prevSelected)
          if (match?.selectable) canvas.setActiveObject(match)
        }
        canvas.requestRenderAll()
        // Re-apply display zoom after clear/rebuild (Fabric may reset CSS size).
        const z = scaleRef.current
        canvas.setDimensions(
          {
            width: `${CANVAS_WIDTH * z}px`,
            height: `${CANVAS_HEIGHT * z}px`,
          },
          { cssOnly: true }
        )
        canvas.calcOffset()
        sceneEpochRef.current += 1
        sceneRecoveriesRef.current = 0
        setSceneError(null)
        const busy = useEditorStore.getState().busyKind
        if (busy === "generating" || busy === "loading-image") {
          setBusyKind("idle")
        }
      } catch (err) {
        if (cancelled) return
        if (process.env.NODE_ENV !== "production") {
          console.error("[fabric-canvas] scene rebuild failed", err)
        }
        if (sceneRecoveriesRef.current >= 3) {
          setSceneError(
            err instanceof Error
              ? err.message
              : "Не удалось собрать сцену холста"
          )
          return
        }
        sceneRecoveriesRef.current += 1
        // Silent recover: reset selected layer + softbox, then rebuild — no crash plate.
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
    }
  }, [
    ready,
    sceneKey,
    rebuildNonce,
    layers,
    productPreviewUrl,
    backgroundPreviewUrl,
    updateLayer,
    syncLayerGeometry,
    setBusyKind,
  ])

  // Softbox updates: imperative store.subscribe — does not re-render this Fabric host.
  // During scrub: CSS overlay only (softboxLivePreview). Fabric paints on scrub end / idle.
  useEffect(() => {
    if (!ready) return

    let debounceTimer = 0
    let raf = 0
    let lastScrubbing: boolean | null = null

    const runApply = () => {
      raf = 0
      try {
        const canvas = fabricRef.current
        if (!isFabricCanvasAlive(canvas)) return
        const state = useEditorStore.getState()
        const useCssOverlay =
          state.softboxScrubbing && !state.backgroundPreviewUrl
        applySoftboxToFabric(canvas!, state.softbox, {
          preview: state.softboxScrubbing,
          hideSoftboxForCssOverlay: useCssOverlay,
        })
      } catch (err) {
        if (process.env.NODE_ENV !== "production") {
          console.error("[fabric-canvas] softbox apply failed", err)
        }
      }
    }

    const schedule = (immediate: boolean) => {
      const state = useEditorStore.getState()
      const scrubbing = state.softboxScrubbing
      const scrubbingChanged = lastScrubbing !== scrubbing
      lastScrubbing = scrubbing

      // Mid-scrub value ticks: CSS overlay is the preview — do not touch Fabric.
      if (scrubbing && !scrubbingChanged && !immediate) {
        return
      }

      window.clearTimeout(debounceTimer)
      if (raf) {
        cancelAnimationFrame(raf)
        raf = 0
      }

      if (immediate || scrubbingChanged) {
        // Scrub end must restore Fabric softbox before React paints without CSS overlay
        // (rAF would flash one empty frame).
        if (immediate && !scrubbing) {
          runApply()
          return
        }
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
      // Ignore softboxLivePreview — CSS overlay owns that channel.
      if (
        state.softbox === prev.softbox &&
        state.softboxScrubbing === prev.softboxScrubbing &&
        state.backgroundPreviewUrl === prev.backgroundPreviewUrl
      ) {
        return
      }
      // Flush final Fabric paint as soon as scrub ends (onChangeCommitted).
      const scrubEnded = prev.softboxScrubbing && !state.softboxScrubbing
      schedule(scrubEnded)
    })

    return () => {
      unsub()
      window.clearTimeout(debounceTimer)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [ready])

  // Undo / external transform patches → Fabric objects
  useEffect(() => {
    const canvas = fabricRef.current
    if (!canvas || writingStoreRef.current || interactingRef.current) return

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
      match.set("opacity", prev)
      canvas.requestRenderAll()
    }, 450)
    return () => window.clearTimeout(t)
  }, [flashLayerId])

  return (
    <div
      id="editor-export-canvas"
      data-export-canvas="true"
      data-fabric-engine="true"
      className={cn(
        "relative overflow-hidden bg-loft shadow-[0_24px_80px_rgba(0,0,0,0.55)] ring-1 ring-white/10"
      )}
      style={{
        width: CANVAS_WIDTH * scale,
        height: CANVAS_HEIGHT * scale,
      }}
      role="img"
      aria-label={`Холст ${CANVAS_WIDTH}×${CANVAS_HEIGHT}`}
      aria-busy={showBusyOverlay}
    >
      <div
        className="relative"
        style={{
          width: CANVAS_WIDTH * scale,
          height: CANVAS_HEIGHT * scale,
        }}
      >
        <SoftboxScrubOverlay />
        <canvas ref={canvasElRef} className="relative z-[1]" />
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
  )
}

export { EditorFabricCanvas }
