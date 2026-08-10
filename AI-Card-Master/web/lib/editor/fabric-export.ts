import type { Canvas as FabricCanvas, FabricObject } from "fabric"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { dataUrlToBlob, downloadBlob } from "@/lib/export/download-blob"

export type FabricExportSize = {
  width: number
  height: number
  label: string
}

/** Marketplace card presets (3:4). */
export const FABRIC_EXPORT_PRESETS: FabricExportSize[] = [
  { width: 1080, height: 1440, label: "1080×1440" },
  { width: 900, height: 1200, label: "900×1200" },
]

type FabricExporter = {
  /** Composite all layers to a PNG data URL at native or custom size. */
  toPngDataUrl: (size?: FabricExportSize) => Promise<string>
  toPngBytes: (size?: FabricExportSize) => Promise<Uint8Array>
  getCanvas: () => FabricCanvas | null
  /**
   * Bumped after each successful 3-layer scene rebuild.
   * Used by multi-page ZIP capture to wait until remount finishes.
   */
  getSceneEpoch: () => number
}

let activeExporter: FabricExporter | null = null

export function registerFabricExporter(exporter: FabricExporter | null): void {
  activeExporter = exporter
}

export function getFabricSceneEpoch(): number {
  return activeExporter?.getSceneEpoch() ?? 0
}

/** Live Fabric instance for the editor canvas (null if unmounted / not ready). */
export function getActiveFabricCanvas(): FabricCanvas | null {
  try {
    return activeExporter?.getCanvas() ?? null
  } catch {
    return null
  }
}

export function isFabricExporterReady(): boolean {
  const canvas = activeExporter?.getCanvas() ?? null
  if (!canvas || !activeExporter) return false
  return (
    activeExporter.getSceneEpoch() > 0 && canvas.getObjects().length > 0
  )
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

/** Wait until Fabric has finished a scene rebuild (after page remount). */
export async function waitForFabricExportReady(
  options?: { minEpoch?: number; timeoutMs?: number }
): Promise<void> {
  const timeoutMs = options?.timeoutMs ?? 12_000
  const minEpoch = options?.minEpoch ?? 1
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const exporter = activeExporter
    const canvas = exporter?.getCanvas() ?? null
    if (
      exporter &&
      canvas &&
      exporter.getSceneEpoch() >= minEpoch &&
      canvas.getObjects().length > 0
    ) {
      return
    }
    await sleep(40)
  }
  throw new Error("Fabric canvas is not ready for export")
}

export async function exportFabricCanvasPng(options?: {
  size?: FabricExportSize
  filename?: string
}): Promise<void> {
  const exporter = activeExporter
  if (!exporter) {
    throw new Error("Fabric canvas is not ready")
  }
  const size = options?.size ?? FABRIC_EXPORT_PRESETS[0]!
  const dataUrl = await exporter.toPngDataUrl(size)
  const blob = dataUrlToBlob(dataUrl)
  const base =
    options?.filename?.replace(/\.(png|webp)$/i, "") ||
    `card-${size.width}x${size.height}`
  downloadBlob(blob, `${base}.png`)
}

export async function captureFabricPngBytes(
  size?: FabricExportSize
): Promise<Uint8Array | null> {
  if (!activeExporter) return null
  return activeExporter.toPngBytes(
    size ?? { width: CANVAS_WIDTH, height: CANVAS_HEIGHT, label: "native" }
  )
}

type ExportChromeObject = FabricObject & {
  isSmartGuide?: boolean
  excludeFromExport?: boolean
  isEditing?: boolean
  exitEditing?: () => void
}

function isExportChrome(obj: FabricObject): boolean {
  const o = obj as ExportChromeObject
  return Boolean(o.isSmartGuide || o.excludeFromExport)
}

/**
 * Strip editor chrome that must never appear in marketplace PNGs:
 * selection borders, transform handles, text caret, smart guides, inline editors.
 */
function prepareCanvasForExport(canvas: FabricCanvas): {
  prevActive: FabricObject | undefined
  hidden: { obj: FabricObject; visible: boolean }[]
} {
  const active = canvas.getActiveObject() as ExportChromeObject | undefined
  if (active?.isEditing && typeof active.exitEditing === "function") {
    active.exitEditing()
  }
  // Exit any orphan inline editors (chip label IText marked excludeFromExport).
  for (const obj of canvas.getObjects()) {
    const o = obj as ExportChromeObject
    if (o.isEditing && typeof o.exitEditing === "function") {
      o.exitEditing()
    }
  }

  const hidden: { obj: FabricObject; visible: boolean }[] = []
  for (const obj of canvas.getObjects()) {
    if (!isExportChrome(obj)) continue
    hidden.push({ obj, visible: obj.visible !== false })
    obj.set("visible", false)
  }

  const prevActive = canvas.getActiveObject() ?? undefined
  canvas.discardActiveObject()
  // Sync paint so lower/upper buffers match before any DOM fallback capture.
  canvas.requestRenderAll()

  return { prevActive, hidden }
}

function restoreCanvasAfterExport(
  canvas: FabricCanvas,
  state: ReturnType<typeof prepareCanvasForExport>
): void {
  for (const { obj, visible } of state.hidden) {
    obj.set("visible", visible)
  }
  if (state.prevActive && canvas.getObjects().includes(state.prevActive)) {
    canvas.setActiveObject(state.prevActive)
  }
  canvas.requestRenderAll()
}

/**
 * Discard selection chrome, hide guides/grid helpers, then rasterize so output
 * matches the requested pixel size (canvas logical size is always 1080×1440).
 */
export async function fabricCanvasToPngDataUrl(
  canvas: FabricCanvas,
  size: FabricExportSize = FABRIC_EXPORT_PRESETS[0]!
): Promise<string> {
  const prepared = prepareCanvasForExport(canvas)
  const multiplier = size.width / CANVAS_WIDTH
  // Editor may use setZoom/absolutePan for Fit — export always at identity VPT
  // so left/top/width/height map to the native 1080×1440 artboard.
  const transform = canvas.viewportTransform
  const prevVpt: [number, number, number, number, number, number] = transform
    ? [
        transform[0] ?? 1,
        transform[1] ?? 0,
        transform[2] ?? 0,
        transform[3] ?? 1,
        transform[4] ?? 0,
        transform[5] ?? 0,
      ]
    : [1, 0, 0, 1, 0, 0]

  try {
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0])
    // Fabric toCanvasElement already sets skipControlsDrawing=true (no handles).
    // filter is belt-and-suspenders for guides / excludeFromExport objects.
    return canvas.toDataURL({
      format: "png",
      multiplier,
      enableRetinaScaling: false,
      left: 0,
      top: 0,
      width: CANVAS_WIDTH,
      height: CANVAS_HEIGHT,
      filter: (obj) => !isExportChrome(obj as FabricObject),
    })
  } finally {
    canvas.setViewportTransform(prevVpt)
    restoreCanvasAfterExport(canvas, prepared)
  }
}

export async function fabricCanvasToPngBytes(
  canvas: FabricCanvas,
  size?: FabricExportSize
): Promise<Uint8Array> {
  const dataUrl = await fabricCanvasToPngDataUrl(canvas, size)
  const blob = dataUrlToBlob(dataUrl)
  const buffer = await blob.arrayBuffer()
  return new Uint8Array(buffer)
}

/**
 * Capture each editor page from the live Fabric canvas at 1080×1440.
 * Switches pages via the store, waits for remount/rebuild, then restores index.
 */
export async function captureFabricPagesPngBytes(options: {
  pageCount: number
  getActivePageIndex: () => number
  setActivePageIndex: (index: number) => void
}): Promise<Uint8Array[]> {
  const pageCount = Math.max(1, Math.floor(options.pageCount))
  const previousIndex = options.getActivePageIndex()
  const results: Uint8Array[] = []
  const nativeSize: FabricExportSize = {
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
    label: "1080×1440",
  }

  try {
    for (let index = 0; index < pageCount; index += 1) {
      if (options.getActivePageIndex() !== index) {
        options.setActivePageIndex(index)
        // React remounts EditorCanvas per page — wait until the previous
        // Fabric instance is disposed (exporter null or epoch reset to 0).
        await sleep(16)
        const teardownStarted = Date.now()
        while (Date.now() - teardownStarted < 3_000) {
          if (!activeExporter || getFabricSceneEpoch() === 0) break
          await sleep(20)
        }
        await waitForFabricExportReady({ minEpoch: 1, timeoutMs: 12_000 })
      } else {
        await waitForFabricExportReady({ minEpoch: 1, timeoutMs: 8_000 })
      }

      const bytes = await captureFabricPngBytes(nativeSize)
      if (!bytes || bytes.byteLength < 2_048) {
        throw new Error(`Failed to capture page ${index + 1} from Fabric canvas`)
      }
      results.push(bytes)
    }
  } finally {
    if (options.getActivePageIndex() !== previousIndex) {
      options.setActivePageIndex(previousIndex)
    }
  }

  return results
}
