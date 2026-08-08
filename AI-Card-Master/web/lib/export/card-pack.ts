import { toBlob, toPng } from "html-to-image"
import JSZip from "jszip"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import {
  assertValidPngBlob,
  dataUrlToBlob,
  downloadBlob,
  imageUrlToDataUrl,
} from "@/lib/export/download-blob"
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
  zipBasename?: string
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

const CAPTURE_BG = "#0f1115"

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

function setSlideBackground(root: HTMLDivElement, imageUrl: string | null) {
  const wash = document.createElement("div")
  wash.style.cssText =
    "position:absolute;inset:0;background:linear-gradient(155deg,#1e2430 0%,#12151b 48%,#0f1115 100%);"
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
 * Main slide prefers the live editor canvas; remaining slides are
 * offscreen infographic renders from the same product assets.
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

  for (const slide of slides) {
    let pngBytes: Uint8Array
    if (slide.kind === "main" && options.canvasEl) {
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
  downloadBlob(archive, `${basename}-pack-${packSize}.zip`)
}

function findEditorExportCanvas(): HTMLElement | null {
  if (typeof document === "undefined") return null
  return document.querySelector<HTMLElement>("[data-export-canvas='true']")
}

export { downloadCardPackZip, findEditorExportCanvas }
