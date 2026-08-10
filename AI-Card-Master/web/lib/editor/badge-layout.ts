/**
 * Dynamic Auto-Padding layout for marketplace badge groups.
 * Plate (Rect) grows with text metrics; icon stays vertically centered
 * on the title + subtitle stack.
 */

import type { FabricObject, Group, Rect, Textbox } from "fabric"

import type { FeatureChipDraft } from "@/types/canvas"

/** Logical padding (CSS px) before CHIP_SOURCE_SCALE. */
export const BADGE_AUTO_PADDING = {
  top: 12,
  right: 16,
  bottom: 12,
  /** Left inset reserved for the icon column. */
  left: 48,
} as const

export type BadgeLayoutParts = {
  bg?: Rect
  icon?: FabricObject
  label?: Textbox
  subtitle?: Textbox
}

export type BadgeLayoutMetrics = {
  hi: number
  padTop: number
  padRight: number
  padBottom: number
  padLeft: number
  iconSize: number
  textStackGap: number
  maxTextWidth: number
}

export type FitBadgeTextOptions = {
  /**
   * Prefer non-mutating canvas measure — skip getBoundingRect / width=1e5 probe.
   * Required while Fabric isEditing: those probes exit edit mode or thrash width.
   */
  preferCalcWidth?: boolean
}

/**
 * True unwrapped width via Canvas2D — does not mutate the Textbox.
 * Fabric's calcTextWidth() during edit often returns the box width, not the
 * overflowing long-run width, so the plate stops growing and glyphs spill out.
 */
export function measureUnwrappedTextWidth(text: Textbox): number {
  const raw = text.text ?? ""
  if (!raw) return 0
  const fontSize = text.fontSize || 16
  const fontFamily = text.fontFamily || "sans-serif"
  const fontWeight = String(text.fontWeight ?? "normal")
  const fontStyle = String(text.fontStyle ?? "normal")

  try {
    const ctx =
      (
        text.canvas as
          | { contextContainer?: CanvasRenderingContext2D }
          | null
          | undefined
      )?.contextContainer ??
      document.createElement("canvas").getContext("2d")
    if (!ctx) return Math.ceil(text.calcTextWidth() || 0)
    ctx.font = `${fontStyle} ${fontWeight} ${fontSize}px ${fontFamily}`
    let max = 0
    for (const line of raw.split(/\r?\n/)) {
      max = Math.max(max, ctx.measureText(line).width)
    }
    return Math.ceil(max)
  } catch {
    return Math.ceil(text.calcTextWidth() || 0)
  }
}

/**
 * Fit Textbox to content width, wrap only after the barrier.
 * Uses word wrap by default; grapheme split only when a run exceeds the barrier
 * (otherwise Fabric wraps the last letter onto a second line — orphan glyph bug).
 */
export function fitBadgeTextboxWidth(
  text: Textbox,
  maxTextWidth: number,
  options?: FitBadgeTextOptions
): number {
  const minW = Math.max(20, text.minWidth || 20)
  const raw = text.text ?? ""
  const hasExplicitNewline = /\r?\n/.test(raw)
  // Safety pad: width === calcTextWidth() makes Fabric wrap the last glyph.
  const pad = Math.max(4, Math.ceil((text.fontSize || 16) * 0.12))
  const editingSafe = Boolean(options?.preferCalcWidth)
  const barrier = Math.max(minW, maxTextWidth)

  let natural: number
  if (editingSafe) {
    natural = Math.max(minW, measureUnwrappedTextWidth(text))
  } else {
    // Measure natural width without wrapping.
    text.set({ width: Math.max(barrier, 1e5), splitByGrapheme: false })
    if (typeof text.initDimensions === "function") text.initDimensions()
    natural = Math.ceil(text.calcTextWidth() || minW)
  }

  // Prefer live bounding box when idle (Dynamic Auto-Padding).
  let fromBounds = 0
  if (!editingSafe) {
    try {
      const br = text.getBoundingRect()
      fromBounds = Math.ceil(br.width / Math.max(0.001, text.scaleX ?? 1))
    } catch {
      fromBounds = 0
    }
  }

  const contentNatural = Math.max(natural, fromBounds || 0)

  // Character wrap when a run cannot fit the canvas barrier in one line.
  const needsGraphemeSplit = contentNatural > barrier
  let nextW = Math.min(Math.max(contentNatural + pad, minW), barrier)

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
      nextW < barrier &&
      guard < 12
    ) {
      nextW = Math.min(nextW + pad, barrier)
      text.set({ width: nextW, splitByGrapheme: false })
      if (typeof text.initDimensions === "function") text.initDimensions()
      guard += 1
    }
  }

  return nextW
}

function measureTextBoxHeight(
  text: Textbox,
  fallback: number,
  preferCalcHeight?: boolean
): number {
  if (!preferCalcHeight) {
    try {
      const br = text.getBoundingRect()
      const fromBounds = Math.ceil(br.height / Math.max(0.001, text.scaleY ?? 1))
      if (Number.isFinite(fromBounds) && fromBounds > 0) {
        return Math.max(fallback * 0.5, fromBounds)
      }
    } catch {
      // Fall through.
    }
  }
  // After initDimensions, height reflects wrapped lines even while editing.
  const h = text.height ?? fallback
  if (Number.isFinite(h) && h > 0) return h

  // Fallback: estimate wrapped line count from unwrapped width.
  const fontSize = text.fontSize || fallback
  const maxW = Math.max(1, text.width || 1)
  const unwrapped = measureUnwrappedTextWidth(text)
  const lines = Math.max(1, Math.ceil(unwrapped / maxW))
  const explicit = (text.text ?? "").split(/\r?\n/).length
  return Math.max(fallback, fontSize * 1.25 * Math.max(lines, explicit))
}

export function buildBadgeLayoutMetrics(args: {
  hi: number
  chip?: FeatureChipDraft
  maxTextWidth: number
}): BadgeLayoutMetrics {
  const { hi, chip, maxTextWidth } = args
  const isGlass = chip?.variant === "glass"
  return {
    hi,
    padTop: BADGE_AUTO_PADDING.top * hi,
    padRight: BADGE_AUTO_PADDING.right * hi,
    padBottom: BADGE_AUTO_PADDING.bottom * hi,
    padLeft: BADGE_AUTO_PADDING.left * hi,
    iconSize: (isGlass ? 22 : 18) * hi,
    textStackGap: 5 * hi,
    maxTextWidth,
  }
}

/**
 * Max Textbox width in chip source coords: grow with typing until the plate
 * would hit the canvas right edge.
 *
 * `groupLeft` is the canvas X of the plate's left edge (Group origin left/top).
 */
export function badgeTextWidthBarrier(args: {
  hi: number
  padLeft: number
  padRight: number
  groupLeft: number
  groupScaleX: number
  canvasWidth: number
  edgeMargin?: number
}): number {
  const chrome = args.padLeft + args.padRight
  const groupScale = Math.max(0.01, args.groupScaleX)
  const edge = args.edgeMargin ?? 24
  const available = args.canvasWidth - args.groupLeft - edge
  // Never force a minimum wider than the remaining artboard (that overflowed).
  const maxPlateVisual = Math.max(48 * args.hi * groupScale, available)
  const maxPlateSource = maxPlateVisual / groupScale
  return Math.max(48 * args.hi, maxPlateSource - chrome)
}

/**
 * Recalculate plate size + child positions from live text metrics.
 * Preserves absolute group left/top across Fabric layout refreshes.
 * @param options.skipGroupUpdate — while nested text is editing, mutate plate
 *   size only (no text left/top, no addWithUpdate) so Fabric stays in edit mode
 *   and the plate does not drift.
 */
export function layoutBadgeGroup(
  group: Group,
  parts: BadgeLayoutParts,
  metrics: BadgeLayoutMetrics,
  options?: { skipGroupUpdate?: boolean }
): void {
  const absoluteLeft = group.left ?? 0
  const absoluteTop = group.top ?? 0

  const { bg, icon, label, subtitle } = parts
  const {
    padTop,
    padRight,
    padBottom,
    padLeft,
    iconSize,
    textStackGap,
    maxTextWidth,
    hi,
  } = metrics

  const editing = Boolean(options?.skipGroupUpdate)
  const labelSize = 16 * hi
  const textWidth = label
    ? fitBadgeTextboxWidth(label, maxTextWidth, {
        preferCalcWidth: editing,
      })
    : 80 * hi
  const subtitleWidth = subtitle
    ? fitBadgeTextboxWidth(subtitle, maxTextWidth, {
        preferCalcWidth: editing,
      })
    : 0

  const hasSubtitle = Boolean(subtitle)
  const labelH = label
    ? measureTextBoxHeight(label, labelSize, editing)
    : labelSize
  const subtitleH = subtitle
    ? measureTextBoxHeight(
        subtitle,
        Math.max(11 * hi, labelSize * 0.72),
        editing
      )
    : 0

  const contentH = hasSubtitle ? labelH + textStackGap + subtitleH : labelH
  const contentW = Math.max(textWidth, subtitleWidth, 48 * hi)
  const newWidth = padLeft + contentW + padRight
  const boxH = contentH + padTop + padBottom

  // ── Live edit path ──────────────────────────────────────────────────
  // Anchor the existing plate top-left; grow/shrink right + down only.
  // Never rewrite the editing Textbox left/top — that exits Fabric edit
  // mode (next Backspace deletes the whole badge) and drifts the plate.
  if (editing) {
    const prevBgLeft = bg?.left ?? -newWidth / 2
    const prevBgTop = bg?.top ?? -boxH / 2
    const textLeft = label?.left ?? prevBgLeft + padLeft
    const labelTop = label?.top ?? prevBgTop + padTop

    if (bg) {
      bg.set({
        originX: "left",
        originY: "top",
        left: prevBgLeft,
        top: prevBgTop,
        width: newWidth,
        height: boxH,
        dirty: true,
      })
      bg.setCoords()
    }

    // Width already set in fitBadgeTextboxWidth — keep left/top untouched.
    if (label) {
      label.set({ dirty: true })
      label.setCoords()
    }

    if (hasSubtitle && subtitle) {
      subtitle.set({
        originX: "left",
        originY: "top",
        left: textLeft,
        top: labelTop + labelH + textStackGap,
        width: subtitleWidth,
        dirty: true,
      })
      subtitle.setCoords()
    }

    if (icon) {
      const stackTop = labelTop
      const stackBottom = hasSubtitle
        ? labelTop + labelH + textStackGap + subtitleH
        : labelTop + labelH
      const stackMidY = (stackTop + stackBottom) / 2
      const iconColCenter = prevBgLeft + padLeft / 2
      icon.set({
        originX: "center",
        originY: "center",
        left: iconColCenter,
        top: stackMidY,
        dirty: true,
      })
      void iconSize
    }

    // Keep canvas left/top fixed. Do NOT assign group.width/height here —
    // Fabric recenters children when group size changes, which shifts the
    // plate while typing. The bg Rect paints at full size without it.
    group.set({
      left: absoluteLeft,
      top: absoluteTop,
      dirty: true,
    })
    group.setCoords()
    group.canvas?.requestRenderAll()
    return
  }

  // ── Idle / full rebuild path ────────────────────────────────────────
  const contentTop = -boxH / 2 + padTop
  const left0 = -newWidth / 2
  const textLeft = left0 + padLeft

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

  // Title + subtitle stack; icon centers on that stack mid-line.
  if (label) {
    label.set({
      originX: "left",
      originY: "top",
      left: textLeft,
      top: contentTop,
      width: textWidth,
    })
  }
  if (hasSubtitle && subtitle && label) {
    const titleTop = label.top ?? contentTop
    subtitle.set({
      originX: "left",
      originY: "top",
      left: textLeft,
      top: titleTop + labelH + textStackGap,
      width: subtitleWidth,
    })
  }

  if (icon) {
    const stackTop = label?.top ?? contentTop
    const stackBottom =
      hasSubtitle && subtitle
        ? (subtitle.top ?? stackTop) + subtitleH
        : stackTop + labelH
    const stackMidY = (stackTop + stackBottom) / 2
    const iconColCenter = left0 + padLeft / 2
    icon.set({
      originX: "center",
      originY: "center",
      left: iconColCenter,
      top: stackMidY,
    })
    void iconSize
  }

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
