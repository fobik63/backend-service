import { toBlob, toPng } from "html-to-image"
import JSZip from "jszip"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { captureFabricPngBytes } from "@/lib/editor/fabric-export"
import {
  assertValidPngBlob,
  dataUrlToBlob,
  downloadBlob,
  imageUrlToDataUrl,
} from "@/lib/export/download-blob"
import type { SoftboxSettings } from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"

/** Number of photos in a generated card pack (1–20). */
export type PackSize = number

export const MIN_PACK_SIZE = 1
export const MAX_PACK_SIZE = 20
export const PRESET_PACK_SIZES: PackSize[] = [1, 2, 3, 4, 5]

export function clampPackSize(size: number): PackSize {
  const n = Number.isFinite(size) ? Math.floor(size) : 5
  return Math.min(MAX_PACK_SIZE, Math.max(MIN_PACK_SIZE, n))
}

export type CardPackSlideKind =
  | "main"
  | "features"
  | "benefits"
  | "composition"
  | "cta"

export type CardPackSlideDef = {
  kind: CardPackSlideKind
  filename: string
  titleRu: string
  titleEn: string
}

export const CARD_PACK_SLIDES: CardPackSlideDef[] = [
  {
    kind: "main",
    filename: "01-main.png",
    titleRu: "Главная",
    titleEn: "Main",
  },
  {
    kind: "features",
    filename: "02-features.png",
    titleRu: "Преимущества",
    titleEn: "Features",
  },
  {
    kind: "benefits",
    filename: "03-benefits.png",
    titleRu: "Польза",
    titleEn: "Benefits",
  },
  {
    kind: "composition",
    filename: "04-composition.png",
    titleRu: "Состав",
    titleEn: "Composition",
  },
  {
    kind: "cta",
    filename: "05-details.png",
    titleRu: "Детали",
    titleEn: "Details",
  },
]

export function resolvePackSlides(packSize: PackSize): CardPackSlideDef[] {
  const n = clampPackSize(packSize)
  if (n <= CARD_PACK_SLIDES.length) {
    return CARD_PACK_SLIDES.slice(0, n)
  }

  const slides: CardPackSlideDef[] = [...CARD_PACK_SLIDES]
  for (let i = CARD_PACK_SLIDES.length; i < n; i++) {
    const base = CARD_PACK_SLIDES[i % CARD_PACK_SLIDES.length]!
    const cycle = Math.floor(i / CARD_PACK_SLIDES.length) + 1
    slides.push({
      ...base,
      filename: `${String(i + 1).padStart(2, "0")}-${base.kind}.png`,
      titleRu: `${base.titleRu} ${cycle}`,
      titleEn: `${base.titleEn} ${cycle}`,
    })
  }
  return slides
}

export type BuildCardPackOptions = {
  packSize: PackSize
  projectTitle: string
  /** Live editor canvas root (preferred for the main slide). */
  canvasEl?: HTMLElement | null
  productImageUrl?: string | null
  layers?: CanvasLayer[]
  /** Immutable page snapshot used for race-free editor exports. */
  pages?: CanvasLayer[][]
  softbox?: SoftboxSettings
  zipBasename?: string
  /**
   * Fixed archive filename (e.g. `card_ai_export.zip`).
   * When set, overrides slugified basename.
   */
  zipFilename?: string
  /** PNG export multiplier (2× / 3× for crisp vectors & fonts). */
  exportScale?: 1 | 2 | 3
  /**
   * Capture each pack page from the live editor (editable pages).
   * When provided, preferred over offscreen infographic renders.
   */
  capturePageAtIndex?: (pageIndex: number) => Promise<Uint8Array>
}

function slugify(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9а-яё]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "card-pack"
  )
}

function chipLabels(layers: CanvasLayer[] | undefined): string[] {
  if (!layers?.length) {
    return ["Хит продаж", "Натуральный состав", "Гарантия качества"]
  }
  const fromChips = layers
    .filter((l) => l.visible && l.chip?.label)
    .map((l) => l.chip!.label.trim())
    .filter(Boolean)
  if (fromChips.length >= 3) return fromChips.slice(0, 6)
  return [
    ...fromChips,
    "Премиум качество",
    "Быстрая доставка",
    "Проверено селлерами",
  ].slice(0, 6)
}

function productTitle(layers: CanvasLayer[] | undefined, fallback: string): string {
  const textLayer = layers?.find(
    (l) => l.visible && l.type === "text" && l.text?.trim()
  )
  return textLayer?.text?.trim() || fallback
}

const CAPTURE_BG = "#0d0f12"

type CaptureOptions = {
  width?: number
  height?: number
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function nextFrame(): Promise<void> {
  await new Promise<void>((resolve) =>
    window.requestAnimationFrame(() => resolve())
  )
}

/** Wait until layout + paint settle after DOM/style mutations. */
async function settleLayout(): Promise<void> {
  await nextFrame()
  await nextFrame()
  if (typeof document !== "undefined" && document.fonts?.ready) {
    try {
      await document.fonts.ready
    } catch {
      // ignore font readiness errors
    }
  }
}

/**
 * Wait for every <img> under `root` to finish loading/decoding.
 * Avoids 0-byte / blank captures when html-to-image races image paint.
 */
async function waitForImages(root: HTMLElement): Promise<void> {
  const images = Array.from(root.querySelectorAll("img"))
  await Promise.all(
    images.map(async (img) => {
      if (!img.getAttribute("src") && !img.src) return

      // Same-origin public assets don't need CORS; keep existing attr if set.
      if (img.complete && img.naturalWidth > 0) {
        try {
          await img.decode()
        } catch {
          // decode can reject for already-broken images; fall through
        }
        return
      }

      await new Promise<void>((resolve, reject) => {
        const onLoad = () => {
          cleanup()
          resolve()
        }
        const onError = () => {
          cleanup()
          reject(new Error(`Image failed to load: ${img.currentSrc || img.src}`))
        }
        const cleanup = () => {
          img.removeEventListener("load", onLoad)
          img.removeEventListener("error", onError)
        }
        img.addEventListener("load", onLoad)
        img.addEventListener("error", onError)
      })

      try {
        await img.decode()
      } catch {
        // non-fatal — paint may still succeed
      }
    })
  )
}

/** Skip editor chrome that must not appear in exported cards. */
function shouldIncludeNode(node: HTMLElement): boolean {
  if (node.dataset?.exportIgnore === "true") return false
  if (node.dataset?.exportChrome === "true") return false
  // Fabric draws selection handles on the upper canvas — never export it.
  if (node.classList?.contains("upper-canvas")) return false
  return true
}

async function captureElementToPngBytes(
  el: HTMLElement,
  options: CaptureOptions = {}
): Promise<Uint8Array> {
  const width = options.width ?? CANVAS_WIDTH
  const height = options.height ?? CANVAS_HEIGHT

  await waitForImages(el)
  await settleLayout()

  const captureOpts = {
    cacheBust: true,
    pixelRatio: 1,
    width,
    height,
    canvasWidth: width,
    canvasHeight: height,
    backgroundColor: CAPTURE_BG,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: "none",
      margin: "0",
      opacity: "1",
    },
    filter: shouldIncludeNode,
  }

  // Warm-up pass: Safari / Chromium sometimes return blank on first paint.
  try {
    await toBlob(el, captureOpts)
  } catch {
    // warm-up is best-effort
  }
  await sleep(40)

  let lastError: unknown
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      let blob = await toBlob(el, captureOpts)
      if (!blob || blob.size < 2_048) {
        // Fallback path via DataURL — more reliable when toBlob returns null.
        const dataUrl = await toPng(el, captureOpts)
        blob = dataUrlToBlob(dataUrl)
      }
      return await assertValidPngBlob(blob)
    } catch (error) {
      lastError = error
      await sleep(80 * (attempt + 1))
      await settleLayout()
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("Failed to capture card PNG")
}

async function captureLiveCanvas(canvasEl: HTMLElement): Promise<Uint8Array> {
  // Prefer native Fabric composite (all 3 layers) when the engine is mounted.
  if (canvasEl.dataset.fabricEngine === "true") {
    const fabricBytes = await captureFabricPngBytes({
      width: CANVAS_WIDTH,
      height: CANVAS_HEIGHT,
      label: "native",
    })
    if (fabricBytes && fabricBytes.byteLength > 2048) {
      return fabricBytes
    }
  }

  const prevWidth = canvasEl.style.width
  const prevHeight = canvasEl.style.height
  const prevTransform = canvasEl.style.transform
  const prevMaxWidth = canvasEl.style.maxWidth
  const prevMaxHeight = canvasEl.style.maxHeight

  // Force native card size so the clone is not a scaled-down preview.
  canvasEl.style.width = `${CANVAS_WIDTH}px`
  canvasEl.style.height = `${CANVAS_HEIGHT}px`
  canvasEl.style.maxWidth = "none"
  canvasEl.style.maxHeight = "none"
  canvasEl.style.transform = "none"

  try {
    await settleLayout()
    return await captureElementToPngBytes(canvasEl)
  } finally {
    canvasEl.style.width = prevWidth
    canvasEl.style.height = prevHeight
    canvasEl.style.maxWidth = prevMaxWidth
    canvasEl.style.maxHeight = prevMaxHeight
    canvasEl.style.transform = prevTransform
  }
}

function buildSlideShell(): { host: HTMLDivElement; root: HTMLDivElement } {
  // Host clips the slide from view; the capture target itself stays opacity:1 —
  // html-to-image copies computed opacity and blanks fully transparent nodes.
  const host = document.createElement("div")
  host.setAttribute("data-card-pack-host", "true")
  host.style.cssText = [
    "position:fixed",
    "left:0",
    "top:0",
    "width:0",
    "height:0",
    "overflow:hidden",
    "pointer-events:none",
    "z-index:-1",
    "opacity:1",
  ].join(";")

  const root = document.createElement("div")
  root.setAttribute("data-card-pack-slide", "true")
  root.style.cssText = [
    `width:${CANVAS_WIDTH}px`,
    `height:${CANVAS_HEIGHT}px`,
    "overflow:hidden",
    "font-family:Montserrat,system-ui,sans-serif",
    "color:#f5f5f4",
    `background:${CAPTURE_BG}`,
    "box-sizing:border-box",
    "position:relative",
    "opacity:1",
  ].join(";")

  host.appendChild(root)
  document.body.appendChild(host)
  return { host, root }
}

function renderEditorPageSnapshot(args: {
  layers: CanvasLayer[]
  imageUrl: string | null
  softbox?: SoftboxSettings
}): Promise<Uint8Array> {
  const { host, root } = buildSlideShell()
  const warmth = args.softbox
    ? Math.max(0, Math.min(1, (6500 - args.softbox.colorTempK) / 3800))
    : 0.25
  const warmAlpha = (0.05 + warmth * 0.12).toFixed(3)
  const coolAlpha = (0.06 + (1 - warmth) * 0.1).toFixed(3)
  root.style.background = args.softbox?.enabled
    ? `linear-gradient(155deg,rgba(93,140,210,${coolAlpha}) 0%,#12151b 48%,rgba(245,158,11,${warmAlpha}) 100%)`
    : "linear-gradient(160deg,#14171d 0%,#0d0f12 100%)"

  for (const layer of [...args.layers].sort((a, b) => a.zIndex - b.zIndex)) {
    if (!layer.visible || layer.type === "background") continue
    const node = document.createElement("div")
    node.dataset.layerId = layer.id
    node.style.cssText = [
      "position:absolute",
      `left:${layer.x ?? 0}%`,
      `top:${layer.y ?? 0}%`,
      `width:${layer.width ?? (layer.type === "shape" ? 36 : 20)}%`,
      `height:${layer.height ?? (layer.type === "shape" ? 9 : 12)}%`,
      `opacity:${layer.opacity}`,
      `z-index:${layer.zIndex}`,
      `transform:rotate(${layer.rotation ?? 0}deg) scale(${layer.scale ?? 1})`,
      "transform-origin:50% 50%",
      "box-sizing:border-box",
    ].join(";")

    if (layer.type === "image") {
      if (!args.imageUrl) continue
      const image = document.createElement("img")
      image.src = args.imageUrl
      image.alt = ""
      image.decoding = "sync"
      image.style.cssText =
        "display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 28px 36px rgba(0,0,0,.4));"
      node.appendChild(image)
    } else if (layer.type === "text") {
      const style = layer.textStyle
      node.textContent = layer.text ?? ""
      node.style.whiteSpace = "pre-wrap"
      node.style.overflowWrap = "break-word"
      node.style.fontFamily = style?.fontFamily ?? "Inter"
      node.style.fontSize = `${style?.fontSize ?? 48}px`
      node.style.fontWeight = String(style?.fontWeight ?? 700)
      node.style.color = style?.color ?? "#FFFFFF"
      node.style.lineHeight = "1.15"
      if (style?.strokeWidth) {
        node.style.webkitTextStroke = `${style.strokeWidth}px ${style.strokeColor}`
      }
      if (style?.shadowEnabled) {
        node.style.textShadow = `${style.shadowOffsetX}px ${style.shadowOffsetY}px ${style.shadowBlur}px ${style.shadowColor}`
      }
    } else if (layer.chip) {
      node.style.display = "flex"
      node.style.flexDirection = "column"
      node.style.alignItems = "center"
      node.style.justifyContent = "center"
      node.style.padding = "12px 18px"
      node.style.borderRadius = `${layer.chip.borderRadius}px`
      node.style.background = layer.chip.bgColor
      node.style.color = layer.chip.textColor ?? "#FFFFFF"
      node.style.fontSize = "24px"
      node.style.fontWeight = "700"
      node.style.textAlign = "center"
      if (layer.chip.variant === "glass") {
        node.style.backdropFilter = `blur(${layer.chip.blur ?? 12}px)`
        node.style.border = `1px solid ${layer.chip.strokeColor ?? "rgba(255,255,255,.18)"}`
      } else if (layer.chip.variant === "dark") {
        node.style.background =
          "linear-gradient(180deg, #3A3E48 0%, #1A1C22 100%)"
        node.style.border = `1px solid ${layer.chip.strokeColor ?? "rgba(255,255,255,.08)"}`
      } else if (layer.chip.variant === "bordered") {
        node.style.background = "transparent"
        node.style.border = `${layer.chip.strokeWidth ?? 3}px solid ${layer.chip.strokeColor ?? "#34D399"}`
      }
      const label = document.createElement("span")
      label.textContent = layer.chip.label
      node.appendChild(label)
      if (layer.chip.subtitle) {
        const subtitle = document.createElement("span")
        subtitle.textContent = layer.chip.subtitle
        subtitle.style.cssText =
          "display:block;margin-top:4px;font-size:14px;font-weight:500;opacity:.78"
        node.appendChild(subtitle)
      }
    }
    root.appendChild(node)
  }

  return captureElementToPngBytes(root).finally(() => host.remove())
}

function setSlideBackground(root: HTMLDivElement, imageUrl: string | null) {
  const wash = document.createElement("div")
  wash.style.cssText =
    "position:absolute;inset:0;background:linear-gradient(155deg,#1a2030 0%,#12151b 48%,#0d0f12 100%);"
  root.appendChild(wash)

  if (imageUrl) {
    const img = document.createElement("img")
    // DataURLs / same-origin assets — do NOT force crossOrigin (breaks some local PNGs).
    img.src = imageUrl
    img.alt = ""
    img.decoding = "sync"
    img.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0.22;filter:blur(18px) saturate(1.1);"
    root.appendChild(img)
  }
}

function appendProductHero(
  root: HTMLDivElement,
  imageUrl: string | null,
  opts: { top?: string; height?: string } = {}
) {
  const frame = document.createElement("div")
  frame.style.cssText = [
    "position:absolute",
    `top:${opts.top ?? "12%"}`,
    "left:50%",
    "transform:translateX(-50%)",
    "width:58%",
    `height:${opts.height ?? "42%"}`,
    "border-radius:28px",
    "overflow:hidden",
    "background:rgba(255,255,255,0.04)",
    "border:1px solid rgba(255,255,255,0.10)",
    "box-shadow:0 28px 80px rgba(0,0,0,0.45)",
  ].join(";")

  if (imageUrl) {
    const img = document.createElement("img")
    img.src = imageUrl
    img.alt = ""
    img.decoding = "sync"
    img.style.cssText =
      "width:100%;height:100%;object-fit:contain;padding:28px;background:radial-gradient(circle at 50% 30%,rgba(5,150,105,0.18),transparent 62%);"
    frame.appendChild(img)
  } else {
    frame.style.display = "flex"
    frame.style.alignItems = "center"
    frame.style.justifyContent = "center"
    frame.textContent = "Product"
    frame.style.fontSize = "42px"
    frame.style.color = "rgba(255,255,255,0.35)"
  }

  root.appendChild(frame)
}

function appendHeading(
  root: HTMLDivElement,
  eyebrow: string,
  title: string,
  top = "58%"
) {
  const wrap = document.createElement("div")
  wrap.style.cssText = [
    "position:absolute",
    `top:${top}`,
    "left:8%",
    "right:8%",
  ].join(";")

  const eye = document.createElement("div")
  eye.textContent = eyebrow
  eye.style.cssText =
    "font-size:22px;letter-spacing:0.18em;text-transform:uppercase;color:#c2a68c;margin-bottom:14px;font-weight:600;"

  const h = document.createElement("div")
  h.textContent = title
  h.style.cssText =
    "font-size:54px;line-height:1.15;font-weight:700;color:#f8fafc;"

  wrap.appendChild(eye)
  wrap.appendChild(h)
  root.appendChild(wrap)
}

function appendChipList(root: HTMLDivElement, labels: string[], top = "72%") {
  const list = document.createElement("div")
  list.style.cssText = [
    "position:absolute",
    `top:${top}`,
    "left:8%",
    "right:8%",
    "display:flex",
    "flex-wrap:wrap",
    "gap:14px",
  ].join(";")

  labels.forEach((label, index) => {
    const chip = document.createElement("div")
    chip.textContent = label
    chip.style.cssText = [
      "padding:14px 22px",
      "border-radius:14px",
      "font-size:26px",
      "font-weight:600",
      index % 2 === 0
        ? "background:#059669;color:#fff"
        : "background:rgba(20,23,29,0.92);color:#f8fafc;border:1px solid rgba(194,166,140,0.35)",
    ].join(";")
    list.appendChild(chip)
  })

  root.appendChild(list)
}

async function renderInfographicSlide(args: {
  kind: Exclude<CardPackSlideKind, "main">
  title: string
  imageUrl: string | null
  labels: string[]
}): Promise<Uint8Array> {
  const { host, root } = buildSlideShell()
  setSlideBackground(root, args.imageUrl)

  try {
    switch (args.kind) {
      case "features": {
        appendProductHero(root, args.imageUrl, { top: "8%", height: "38%" })
        appendHeading(root, "Инфографика · 02", args.title, "50%")
        appendChipList(root, args.labels.slice(0, 4), "68%")
        break
      }
      case "benefits": {
        appendHeading(root, "Инфографика · 03", "Почему выбирают", "8%")
        appendProductHero(root, args.imageUrl, { top: "20%", height: "34%" })
        appendChipList(
          root,
          args.labels.slice(0, 3).map((l) => `✓ ${l}`),
          "62%"
        )
        break
      }
      case "composition": {
        appendHeading(root, "Инфографика · 04", "Состав и свойства", "10%")
        const grid = document.createElement("div")
        grid.style.cssText = [
          "position:absolute",
          "top:28%",
          "left:8%",
          "right:8%",
          "display:grid",
          "grid-template-columns:1fr 1fr",
          "gap:18px",
        ].join(";")
        const cells = [
          args.labels[0] ?? "Натуральные компоненты",
          args.labels[1] ?? "Без парабенов",
          args.labels[2] ?? "Клинически проверено",
          args.labels[3] ?? "Подходит ежедневно",
        ]
        cells.forEach((text) => {
          const cell = document.createElement("div")
          cell.textContent = text
          cell.style.cssText =
            "min-height:220px;display:flex;align-items:center;justify-content:center;text-align:center;padding:28px;border-radius:22px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);font-size:30px;font-weight:600;line-height:1.3;"
          grid.appendChild(cell)
        })
        root.appendChild(grid)
        if (args.imageUrl) {
          const thumb = document.createElement("img")
          thumb.src = args.imageUrl
          thumb.alt = ""
          thumb.decoding = "sync"
          thumb.style.cssText =
            "position:absolute;bottom:7%;left:50%;transform:translateX(-50%);width:28%;height:18%;object-fit:contain;opacity:0.95;"
          root.appendChild(thumb)
        }
        break
      }
      case "cta": {
        appendProductHero(root, args.imageUrl, { top: "10%", height: "46%" })
        appendHeading(root, "Инфографика · 05", args.title, "62%")
        const cta = document.createElement("div")
        cta.textContent = args.labels[0] ?? "Готово к публикации на Ozon / WB"
        cta.style.cssText =
          "position:absolute;left:8%;right:8%;bottom:10%;padding:22px 28px;border-radius:18px;background:linear-gradient(90deg,#059669,#0f766e);font-size:28px;font-weight:700;text-align:center;box-shadow:0 18px 50px rgba(5,150,105,0.35);"
        root.appendChild(cta)
        break
      }
    }

    await waitForImages(root)
    await settleLayout()
    return await captureElementToPngBytes(root)
  } finally {
    host.remove()
  }
}

/**
 * Build a marketplace card pack ZIP (1–20 PNGs) and download it.
 * Prefer live per-page Fabric captures when `capturePageAtIndex` is set;
 * otherwise fall back to page DOM snapshots / offscreen infographic renders.
 */
async function downloadCardPackZip(options: BuildCardPackOptions): Promise<void> {
  const packSize = clampPackSize(options.packSize)
  const slides = resolvePackSlides(packSize)
  const title = productTitle(options.layers, options.projectTitle)
  const labels = chipLabels(options.layers)

  // Prefetch product image into a DataURL so ZIP PNGs never depend on
  // 0-byte Blobs / racey network loads during html-to-image cloning.
  let imageUrl: string | null = null
  if (options.productImageUrl) {
    try {
      imageUrl = await imageUrlToDataUrl(options.productImageUrl)
    } catch {
      // Keep absolute URL as a fallback if DataURL conversion fails.
      imageUrl = options.productImageUrl
    }
  }

  const zip = new JSZip()
  const folder = zip.folder("cards") ?? zip

  for (let index = 0; index < slides.length; index += 1) {
    const slide = slides[index]!
    let pngBytes: Uint8Array

    // Live Fabric capture first — exact 1080×1440 composite (no selection chrome).
    if (options.capturePageAtIndex) {
      pngBytes = await options.capturePageAtIndex(index)
    } else {
      const snapshotLayers = options.pages?.[index]
      if (snapshotLayers) {
        pngBytes = await renderEditorPageSnapshot({
          layers: snapshotLayers,
          imageUrl,
          softbox: options.softbox,
        })
      } else if (slide.kind === "main" && options.canvasEl) {
        pngBytes = await captureLiveCanvas(options.canvasEl)
      } else if (slide.kind === "main") {
        // Fallback main card when canvas is unavailable (e.g. projects grid).
        pngBytes = await renderInfographicSlide({
          kind: "cta",
          title,
          imageUrl,
          labels,
        })
      } else {
        pngBytes = await renderInfographicSlide({
          kind: slide.kind,
          title,
          imageUrl,
          labels,
        })
      }
    }

    // Pass raw bytes (not Blob) so JSZip always writes binary PNG correctly.
    folder.file(slide.filename, pngBytes, { binary: true })
  }

  const basename = slugify(options.zipBasename ?? options.projectTitle)
  const archive = await zip.generateAsync({
    type: "blob",
    compression: "DEFLATE",
    compressionOptions: { level: 6 },
  })
  if (!archive || archive.size <= 0) {
    throw new Error("ZIP archive is empty")
  }
  const filename =
    options.zipFilename?.trim() ||
    `${basename}-pack-${packSize}.zip`
  downloadBlob(archive, filename.endsWith(".zip") ? filename : `${filename}.zip`)
}

function findEditorExportCanvas(): HTMLElement | null {
  if (typeof document === "undefined") return null
  return document.querySelector<HTMLElement>("[data-export-canvas='true']")
}

/** Wait two animation frames so React can commit the active page. */
async function waitForPaint(): Promise<void> {
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve())
    })
  })
  await sleep(40)
}

/**
 * Capture the live editor canvas and trigger a direct download (PNG / WebP).
 */
async function downloadCurrentCanvasImage(options: {
  canvasEl?: HTMLElement | null
  filename: string
  format?: "png" | "webp"
  /** Export multiplier (default 2×). */
  exportScale?: 1 | 2 | 3
}): Promise<void> {
  const format = options.format ?? "png"
  const scale = options.exportScale ?? 2
  const exportW = Math.round(CANVAS_WIDTH * scale)
  const exportH = Math.round(CANVAS_HEIGHT * scale)

  // Prefer Fabric native export (exact layer composite at artboard × scale).
  const fabricBytes = await captureFabricPngBytes({
    width: exportW,
    height: exportH,
    label: `${exportW}×${exportH}`,
  })
  if (fabricBytes && fabricBytes.byteLength > 2048) {
    const pngBlob = new Blob([Uint8Array.from(fabricBytes)], {
      type: "image/png",
    })
    if (format === "png") {
      downloadBlob(
        pngBlob,
        options.filename.endsWith(".png")
          ? options.filename
          : `${options.filename}.png`
      )
      return
    }
    try {
      const bitmap = await createImageBitmap(pngBlob)
      const canvas = document.createElement("canvas")
      canvas.width = bitmap.width
      canvas.height = bitmap.height
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new Error("2D context unavailable")
      ctx.drawImage(bitmap, 0, 0)
      bitmap.close()
      const webpBlob = await new Promise<Blob | null>((resolve) => {
        canvas.toBlob((blob) => resolve(blob), "image/webp", 0.92)
      })
      if (!webpBlob || webpBlob.size < 256) throw new Error("WebP encode failed")
      downloadBlob(
        webpBlob,
        options.filename.replace(/\.png$/i, "").endsWith(".webp")
          ? options.filename
          : `${options.filename.replace(/\.png$/i, "")}.webp`
      )
      return
    } catch {
      downloadBlob(pngBlob, options.filename.replace(/\.webp$/i, ".png"))
      return
    }
  }

  const canvasEl = options.canvasEl ?? findEditorExportCanvas()
  if (!canvasEl) {
    throw new Error("Editor canvas not found")
  }

  const pngBytes = await captureLiveCanvas(canvasEl)
  const pngBlob = new Blob([Uint8Array.from(pngBytes)], { type: "image/png" })

  if (format === "png") {
    downloadBlob(pngBlob, options.filename.endsWith(".png")
      ? options.filename
      : `${options.filename}.png`)
    return
  }

  // WebP: re-encode via Offscreen/canvas when supported; else fall back to PNG.
  try {
    const bitmap = await createImageBitmap(pngBlob)
    const canvas = document.createElement("canvas")
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const ctx = canvas.getContext("2d")
    if (!ctx) throw new Error("2D context unavailable")
    ctx.drawImage(bitmap, 0, 0)
    bitmap.close()

    const webpBlob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((blob) => resolve(blob), "image/webp", 0.92)
    })
    if (!webpBlob || webpBlob.size < 256) {
      throw new Error("WebP encode failed")
    }
    downloadBlob(
      webpBlob,
      options.filename.replace(/\.png$/i, "").endsWith(".webp")
        ? options.filename
        : `${options.filename.replace(/\.png$/i, "")}.webp`
    )
  } catch {
    downloadBlob(
      pngBlob,
      options.filename.replace(/\.webp$/i, ".png")
    )
  }
}

export {
  captureLiveCanvas,
  downloadCardPackZip,
  downloadCurrentCanvasImage,
  findEditorExportCanvas,
  waitForPaint,
}
