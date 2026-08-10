/**
 * Live in-place badge color updates (no Fabric Group rebuild).
 * During palette scrub: paint fills only — never touch the icon / Zustand.
 */

import {
  FabricImage,
  Gradient,
  Group,
  type FabricObject,
  type Textbox,
} from "fabric"

import {
  resolveChipGradient,
  resolveChipStrokeColor,
  resolveChipStrokeWidth,
} from "@/lib/editor/badge-styles"
import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import { chipIconDataUrl, chipTextColor } from "@/lib/editor/fabric-icons"
import type { FeatureChipDraft } from "@/types/canvas"

type ChipPart = "bg" | "icon" | "label" | "subtitle"

type ChipEngineObject = FabricObject & {
  layerId?: string
  chipPart?: ChipPart
  chipSourceScale?: number
}

/** Matches fabric-canvas CHIP_SOURCE_SCALE. */
const CHIP_SOURCE_SCALE = 3

const lastIconFg = new Map<string, string>()

let appearanceScrubbing = false
let paintRaf = 0
let pendingPaint: { layerId: string; chip: FeatureChipDraft } | null = null

/** True while the color picker / appearance slider is being dragged. */
export function isChipAppearanceScrubbing(): boolean {
  return appearanceScrubbing
}

export function setChipAppearanceScrubbing(active: boolean): void {
  appearanceScrubbing = active
}

/** Call after building / replacing a chip icon so flush can skip no-op reloads. */
export function rememberChipIconFg(layerId: string, fg: string): void {
  lastIconFg.set(layerId, fg)
}

function chipPartOf(
  obj: FabricObject,
  part: ChipPart
): FabricObject | undefined {
  return (obj as ChipEngineObject).chipPart === part ? obj : undefined
}

function findChipGroup(layerId: string): Group | null {
  const canvas = getActiveFabricCanvas()
  if (!canvas) return null
  const hit = canvas
    .getObjects()
    .find((o) => (o as ChipEngineObject).layerId === layerId)
  return hit instanceof Group ? hit : null
}

function loadHtmlImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const el = new Image()
    el.onload = () => resolve(el)
    el.onerror = () => reject(new Error("chip icon decode failed"))
    el.src = url
  })
}

export function resolveChipForeground(chip: FeatureChipDraft): string {
  const isGlass = chip.variant === "glass"
  const isDark = chip.variant === "dark"
  const isBordered = chip.variant === "bordered"
  return (
    chip.textColor ??
    (isGlass || isDark || isBordered || (chip.blur ?? 0) > 0
      ? "#FFFFFF"
      : chipTextColor(chip.bgColor))
  )
}

function resolveChipFill(chip: FeatureChipDraft, bg: FabricObject) {
  const gradientStops = resolveChipGradient(chip)
  if (gradientStops) {
    const w = Math.max(1, bg.width ?? 1)
    const h = Math.max(1, bg.height ?? 1)
    return new Gradient({
      type: "linear",
      gradientUnits: "pixels",
      coords: { x1: 0, y1: 0, x2: 0, y2: h },
      colorStops: [
        { offset: 0, color: gradientStops[0] },
        { offset: 1, color: gradientStops[1] },
      ],
    })
  }
  return chip.bgColor
}

function paintFillsNow(layerId: string, chip: FeatureChipDraft): void {
  const canvas = getActiveFabricCanvas()
  const group = findChipGroup(layerId)
  if (!canvas || !group) return

  const fg = resolveChipForeground(chip)
  const hi = Math.max(
    1,
    (group as ChipEngineObject).chipSourceScale ?? CHIP_SOURCE_SCALE
  )
  const children = group.getObjects()
  const bg = children.find((o) => chipPartOf(o, "bg"))
  const label = children.find((o) => chipPartOf(o, "label")) as
    | Textbox
    | undefined
  const subtitle = children.find((o) => chipPartOf(o, "subtitle")) as
    | Textbox
    | undefined

  let dirty = false
  if (bg) {
    const fill = resolveChipFill(chip, bg)
    const stroke = resolveChipStrokeColor(chip)
    const strokeWidth = resolveChipStrokeWidth(chip) * hi
    const radius = (chip.borderRadius ?? 12) * hi
    bg.set({
      fill,
      stroke,
      strokeWidth,
      rx: radius,
      ry: radius,
    })
    dirty = true
  }
  if (label && label.fill !== fg) {
    label.set("fill", fg)
    dirty = true
  }
  if (subtitle && subtitle.fill !== fg) {
    subtitle.set("fill", fg)
    dirty = true
  }

  if (!dirty) return
  group.set("dirty", true)
  canvas.requestRenderAll()
}

/**
 * Sync plate + label/subtitle fills. Coalesced to one paint per animation frame.
 * Never recolors the icon here — that is flush-only (avoids ghost SVG frames).
 */
export function applyChipLiveColors(
  layerId: string,
  chip: FeatureChipDraft,
  options?: { immediate?: boolean }
): void {
  if (options?.immediate) {
    if (paintRaf) {
      cancelAnimationFrame(paintRaf)
      paintRaf = 0
      pendingPaint = null
    }
    paintFillsNow(layerId, chip)
    return
  }

  pendingPaint = { layerId, chip }
  if (paintRaf) return
  paintRaf = requestAnimationFrame(() => {
    paintRaf = 0
    const job = pendingPaint
    pendingPaint = null
    if (!job) return
    paintFillsNow(job.layerId, job.chip)
  })
}

async function recolorChipIcon(
  layerId: string,
  group: Group,
  chip: FeatureChipDraft,
  fg: string
): Promise<void> {
  const icon = group.getObjects().find((o) => chipPartOf(o, "icon"))
  if (!(icon instanceof FabricImage)) return

  const hi = Math.max(
    1,
    (group as ChipEngineObject).chipSourceScale ?? CHIP_SOURCE_SCALE
  )
  const isGlass = chip.variant === "glass"
  const iconSize = (isGlass ? 22 : 18) * hi
  const iconSrcPx = Math.max(192, Math.round(iconSize * 2))
  const url = chipIconDataUrl(chip.iconId, fg, iconSrcPx)

  const left = icon.left
  const top = icon.top
  const originX = icon.originX
  const originY = icon.originY

  try {
    const el = await loadHtmlImage(url)
    const canvas = group.canvas
    if (!canvas || !canvas.getObjects().includes(group)) return
    if (findChipGroup(layerId) !== group) return

    const nw = Math.max(1, el.naturalWidth || iconSrcPx)
    const nh = Math.max(1, el.naturalHeight || iconSrcPx)
    const scale = iconSize / nw

    icon.setElement(el)
    icon.set({
      width: nw,
      height: nh,
      scaleX: scale,
      scaleY: scale,
      left,
      top,
      originX,
      originY,
      dirty: true,
      objectCaching: false,
    })
    icon.setCoords()
    lastIconFg.set(layerId, fg)
    group.set("dirty", true)
    canvas.requestRenderAll()
  } catch {
    // Icon recolor is best-effort on commit.
  }
}

/** Recolor icon once when the OS color picker closes / scrub ends. */
export function flushChipLiveIcon(
  layerId: string,
  chip: FeatureChipDraft
): void {
  if (paintRaf) {
    cancelAnimationFrame(paintRaf)
    paintRaf = 0
  }
  pendingPaint = null
  paintFillsNow(layerId, chip)

  const fg = resolveChipForeground(chip)
  // Background-only scrubs keep the same fg — skip SVG reload (avoids ghost frames).
  if (lastIconFg.get(layerId) === fg) return

  const group = findChipGroup(layerId)
  if (!group) return
  void recolorChipIcon(layerId, group, chip, fg)
}
