import { toPng } from "html-to-image"
import JSZip from "jszip"

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { dataUrlToBlob, downloadBlob } from "@/lib/export/download-blob"
import type { CanvasLayer } from "@/types/canvas"

export type PackSize = 1 | 3 | 5

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
  return CARD_PACK_SLIDES.slice(0, packSize)
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

async function captureElement(el: HTMLElement): Promise<Blob> {
  const dataUrl = await toPng(el, {
    cacheBust: true,
    pixelRatio: 1,
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
    style: {
      width: `${CANVAS_WIDTH}px`,
      height: `${CANVAS_HEIGHT}px`,
      transform: "none",
    },
  })
  return dataUrlToBlob(dataUrl)
}

async function captureLiveCanvas(canvasEl: HTMLElement): Promise<Blob> {
  const prevWidth = canvasEl.style.width
  const prevHeight = canvasEl.style.height
  const prevTransform = canvasEl.style.transform

  canvasEl.style.width = `${CANVAS_WIDTH}px`
  canvasEl.style.height = `${CANVAS_HEIGHT}px`
  canvasEl.style.transform = "none"

  try {
    return await captureElement(canvasEl)
  } finally {
    canvasEl.style.width = prevWidth
    canvasEl.style.height = prevHeight
    canvasEl.style.transform = prevTransform
  }
}

function buildSlideShell(): HTMLDivElement {
  const root = document.createElement("div")
  root.setAttribute("data-card-pack-slide", "true")
  root.style.cssText = [
    "position:fixed",
    "left:-10000px",
    "top:0",
    `width:${CANVAS_WIDTH}px`,
    `height:${CANVAS_HEIGHT}px`,
    "overflow:hidden",
    "font-family:Montserrat,Inter,system-ui,sans-serif",
    "color:#f5f5f4",
    "background:#0f1115",
    "box-sizing:border-box",
  ].join(";")
  document.body.appendChild(root)
  return root
}

function setSlideBackground(root: HTMLDivElement, imageUrl: string | null) {
  const wash = document.createElement("div")
  wash.style.cssText =
    "position:absolute;inset:0;background:linear-gradient(155deg,#1e2430 0%,#12151b 48%,#0f1115 100%);"
  root.appendChild(wash)

  if (imageUrl) {
    const img = document.createElement("img")
    img.src = imageUrl
    img.crossOrigin = "anonymous"
    img.alt = ""
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
    img.crossOrigin = "anonymous"
    img.alt = ""
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
}): Promise<Blob> {
  const root = buildSlideShell()
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
          thumb.crossOrigin = "anonymous"
          thumb.alt = ""
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

    // Let images paint before snapshot.
    await new Promise((r) => window.setTimeout(r, 120))
    return await captureElement(root)
  } finally {
    root.remove()
  }
}

/**
 * Build a marketplace card pack ZIP (1 / 3 / 5 PNGs) and download it.
 * Main slide prefers the live editor canvas; remaining slides are
 * offscreen infographic renders from the same product assets.
 */
async function downloadCardPackZip(options: BuildCardPackOptions): Promise<void> {
  const slides = resolvePackSlides(options.packSize)
  const title = productTitle(options.layers, options.projectTitle)
  const labels = chipLabels(options.layers)
  const imageUrl = options.productImageUrl ?? null
  const zip = new JSZip()
  const folder = zip.folder("cards") ?? zip

  for (const slide of slides) {
    let blob: Blob
    if (slide.kind === "main" && options.canvasEl) {
      blob = await captureLiveCanvas(options.canvasEl)
    } else if (slide.kind === "main") {
      // Fallback main card when canvas is unavailable (e.g. projects grid).
      blob = await renderInfographicSlide({
        kind: "cta",
        title,
        imageUrl,
        labels,
      })
    } else {
      blob = await renderInfographicSlide({
        kind: slide.kind,
        title,
        imageUrl,
        labels,
      })
    }
    folder.file(slide.filename, blob)
  }

  const basename = slugify(options.zipBasename ?? options.projectTitle)
  const archive = await zip.generateAsync({ type: "blob" })
  downloadBlob(archive, `${basename}-pack-${options.packSize}.zip`)
}

function findEditorExportCanvas(): HTMLElement | null {
  if (typeof document === "undefined") return null
  return document.querySelector<HTMLElement>("[data-export-canvas='true']")
}

export { downloadCardPackZip, findEditorExportCanvas }
