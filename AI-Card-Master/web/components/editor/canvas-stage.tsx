"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { ImageWithSkeleton } from "@/components/ui/image-with-skeleton"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import {
  useEditorStore,
  type EditorZoomMode,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

const RULER_SIZE = 24
const ZOOM_OPTIONS: { mode: EditorZoomMode; label: string }[] = [
  { mode: "50", label: "50%" },
  { mode: "100", label: "100%" },
  { mode: "fit", label: "Fit" },
]

function resolveZoomScale(
  mode: EditorZoomMode,
  fitScale: number
): number {
  if (mode === "50") return 0.5
  if (mode === "100") return 1
  return fitScale
}

function warmthFromKelvin(k: number): number {
  return clamp01((6500 - k) / (6500 - 2700))
}

function clamp01(n: number) {
  return Math.min(1, Math.max(0, n))
}

function softboxBackground(softbox: SoftboxSettings): string {
  if (!softbox.enabled) {
    return "linear-gradient(160deg, #1a1d24 0%, #0f1115 100%)"
  }

  const warmth = warmthFromKelvin(softbox.colorTempK)
  const lightColor = `color-mix(in srgb, #f8fafc ${Math.round((1 - warmth) * 100)}%, #f59e0b ${Math.round(warmth * 100)}%)`
  const soft = 14 + (softbox.softboxDiffusion / 100) * 36
  const intensity = softbox.intensity / 100
  const rad = (softbox.lightAngle * Math.PI) / 180
  const elevFactor = 0.55 + ((softbox.lightElevation - 10) / 80) * 0.45
  const x = 50 + Math.cos(rad) * 38 * elevFactor
  const y = 50 - Math.sin(rad) * 38 * elevFactor

  return `
    radial-gradient(
      circle at ${x}% ${y}%,
      color-mix(in srgb, ${lightColor} ${Math.round(Math.min(intensity, 2) * 50)}%, transparent) 0%,
      transparent ${soft}%
    ),
    linear-gradient(160deg, #1a1d24 0%, #0f1115 100%)
  `
}

function RulerMarks({
  length,
  scale,
  axis,
}: {
  length: number
  scale: number
  axis: "x" | "y"
}) {
  const marks = useMemo(() => {
    const step = scale >= 0.75 ? 100 : scale >= 0.45 ? 200 : 300
    const items: { pos: number; major: boolean; label: string }[] = []
    for (let v = 0; v <= length; v += step / 2) {
      const major = v % step === 0
      items.push({
        pos: v * scale,
        major,
        label: major ? String(v) : "",
      })
    }
    return items
  }, [length, scale])

  if (axis === "x") {
    return (
      <div className="relative h-full w-full">
        {marks.map((m) => (
          <div
            key={`x-${m.pos}`}
            className="absolute top-0 flex flex-col items-center"
            style={{ left: m.pos }}
          >
            <span
              className={cn(
                "w-px bg-white/25",
                m.major ? "h-2.5" : "h-1.5"
              )}
            />
            {m.label ? (
              <span className="mt-0.5 translate-x-1/2 text-[9px] leading-none text-muted-foreground">
                {m.label}
              </span>
            ) : null}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="relative h-full w-full">
      {marks.map((m) => (
        <div
          key={`y-${m.pos}`}
          className="absolute left-0 flex items-center"
          style={{ top: m.pos }}
        >
          <span
            className={cn(
              "h-px bg-white/25",
              m.major ? "w-2.5" : "w-1.5"
            )}
          />
          {m.label ? (
            <span className="ml-0.5 translate-y-1/2 text-[9px] leading-none text-muted-foreground [writing-mode:vertical-lr] rotate-180">
              {m.label}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function CanvasPreview({
  scale,
  softbox,
}: {
  scale: number
  softbox: SoftboxSettings
}) {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)

  const visible = (id: string) =>
    layers.find((l) => l.id === id)?.visible !== false

  const opacityOf = (id: string) =>
    layers.find((l) => l.id === id)?.opacity ?? 1

  const selected = (id: string) => selectedLayerId === id

  const rad = (softbox.lightAngle * Math.PI) / 180
  const cast =
    softbox.enabled
      ? 0.55 - ((softbox.lightElevation - 10) / 80) * 0.42
      : 0
  const shadowX = softbox.enabled ? -Math.cos(rad) * 28 * (0.7 + cast) : 0
  const shadowY = softbox.enabled
    ? 8 + Math.max(0.15, cast) * 28
    : 8
  const shadowBlur = softbox.enabled
    ? 18 + (softbox.softboxDiffusion / 100) * 40
    : 24

  const showBusyOverlay =
    busyKind === "generating" ||
    busyKind === "removing-bg" ||
    busyKind === "loading-image"

  return (
    <div
      className="relative overflow-hidden bg-loft shadow-[0_24px_80px_rgba(0,0,0,0.55)] ring-1 ring-white/10"
      style={{
        width: CANVAS_WIDTH * scale,
        height: CANVAS_HEIGHT * scale,
        background: softboxBackground(softbox),
      }}
      role="img"
      aria-label={`Холст ${CANVAS_WIDTH}×${CANVAS_HEIGHT}`}
      aria-busy={showBusyOverlay}
    >
      {/* Product silhouette / uploaded preview */}
      {visible("layer_product") ? (
        <button
          type="button"
          onClick={() => selectLayer("layer_product")}
          className={cn(
            "absolute left-1/2 top-[42%] h-[38%] w-[46%] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[18%] border border-white/15 outline-none",
            !productPreviewUrl &&
              "bg-gradient-to-b from-copper/45 to-sage/55",
            selected("layer_product") &&
              "ring-2 ring-emerald ring-offset-2 ring-offset-transparent"
          )}
          style={{
            opacity: opacityOf("layer_product"),
            boxShadow: `${shadowX * scale}px ${shadowY * scale}px ${shadowBlur * scale}px rgba(0,0,0,0.55)`,
          }}
          aria-label="Слой товара"
        >
          {productPreviewUrl ? (
            <ImageWithSkeleton
              src={productPreviewUrl}
              alt="Товар на холсте"
              className="absolute inset-0 size-full"
              skeletonClassName="rounded-none"
            />
          ) : null}
        </button>
      ) : null}

      {/* Title */}
      {visible("layer_title") ? (
        <button
          type="button"
          onClick={() => selectLayer("layer_title")}
          className={cn(
            "absolute left-[8%] right-[8%] top-[68%] text-left outline-none",
            selected("layer_title") && "ring-2 ring-emerald/80 rounded-md"
          )}
          style={{ opacity: opacityOf("layer_title") }}
        >
          <span
            className="block font-heading font-semibold tracking-tight text-foreground"
            style={{ fontSize: Math.max(14, 42 * scale) }}
          >
            Sage Mist
          </span>
          <span
            className="mt-1 block text-copper/90"
            style={{ fontSize: Math.max(10, 20 * scale) }}
          >
            Крем для рук · 75 мл
          </span>
        </button>
      ) : null}

      {/* Badge */}
      {visible("layer_badge") ? (
        <button
          type="button"
          onClick={() => selectLayer("layer_badge")}
          className={cn(
            "absolute top-[6%] right-[7%] rounded-md bg-emerald/90 px-3 py-1.5 font-heading font-semibold text-loft outline-none",
            selected("layer_badge") && "ring-2 ring-white/70"
          )}
          style={{
            opacity: opacityOf("layer_badge"),
            fontSize: Math.max(10, 18 * scale),
          }}
        >
          Хит
        </button>
      ) : null}

      {/* Icon plaque */}
      {visible("layer_icon") ? (
        <button
          type="button"
          onClick={() => selectLayer("layer_icon")}
          className={cn(
            "absolute bottom-[7%] left-[8%] flex items-center gap-2 rounded-lg border border-white/12 bg-loft-surface/80 px-3 py-2 outline-none backdrop-blur-sm",
            selected("layer_icon") && "ring-2 ring-emerald"
          )}
          style={{ opacity: opacityOf("layer_icon") }}
        >
          <span
            className="grid size-7 place-items-center rounded-md bg-sage/60 text-emerald"
            style={{ fontSize: Math.max(12, 16 * scale) }}
          >
            ✓
          </span>
          <span
            className="text-left text-muted-foreground"
            style={{ fontSize: Math.max(9, 14 * scale) }}
          >
            Натуральный
            <br />
            состав
          </span>
        </button>
      ) : null}

      {showBusyOverlay ? (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-loft/55 backdrop-blur-[2px]">
          <Skeleton className="h-[38%] w-[46%] rounded-[18%]" />
          <p className="text-xs text-muted-foreground">
            {busyKind === "generating"
              ? "Генерация карточки…"
              : busyKind === "removing-bg"
                ? "Вырезаем фон…"
                : "Загрузка изображения…"}
          </p>
        </div>
      ) : null}

      <span className="pointer-events-none absolute bottom-2 right-3 font-mono text-[10px] text-white/25">
        {CANVAS_WIDTH}×{CANVAS_HEIGHT}
      </span>
    </div>
  )
}

function EditorCanvasStage() {
  const zoomMode = useEditorStore((s) => s.zoomMode)
  const setZoomMode = useEditorStore((s) => s.setZoomMode)
  const softbox = useEditorStore((s) => s.softbox)

  const viewportRef = useRef<HTMLDivElement>(null)
  const [fitScale, setFitScale] = useState(0.35)

  useEffect(() => {
    const el = viewportRef.current
    if (!el) return

    const measure = () => {
      const pad = 48
      const availW = Math.max(120, el.clientWidth - RULER_SIZE - pad)
      const availH = Math.max(120, el.clientHeight - RULER_SIZE - pad)
      const next = Math.min(availW / CANVAS_WIDTH, availH / CANVAS_HEIGHT)
      setFitScale(Math.max(0.12, Math.min(1, next)))
    }

    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const scale = resolveZoomScale(zoomMode, fitScale)
  const scaledW = CANVAS_WIDTH * scale
  const scaledH = CANVAS_HEIGHT * scale

  return (
    <section
      className="relative flex min-w-0 flex-1 flex-col bg-loft"
      aria-label="Область предпросмотра"
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/8 px-4">
        <p className="text-xs text-muted-foreground">
          Холст{" "}
          <span className="font-mono text-foreground/80">
            {CANVAS_WIDTH}×{CANVAS_HEIGHT}
          </span>
        </p>
        <div
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-loft-surface/80 p-0.5"
          role="group"
          aria-label="Масштаб"
        >
          {ZOOM_OPTIONS.map((opt) => (
            <Button
              key={opt.mode}
              type="button"
              size="xs"
              variant={zoomMode === opt.mode ? "secondary" : "ghost"}
              className={cn(
                "min-w-11",
                zoomMode === opt.mode && "bg-emerald/20 text-emerald"
              )}
              onClick={() => setZoomMode(opt.mode)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </div>

      <div ref={viewportRef} className="relative min-h-0 flex-1 overflow-auto">
        <div
          className="sticky top-0 z-10 grid bg-loft-surface/95 backdrop-blur-sm"
          style={{
            gridTemplateColumns: `${RULER_SIZE}px 1fr`,
            height: RULER_SIZE,
            minWidth: RULER_SIZE + scaledW,
          }}
        >
          <div className="border-b border-r border-white/10 bg-loft-surface" />
          <div
            className="overflow-hidden border-b border-white/10"
            style={{ width: scaledW }}
          >
            <RulerMarks length={CANVAS_WIDTH} scale={scale} axis="x" />
          </div>
        </div>

        <div
          className="grid"
          style={{
            gridTemplateColumns: `${RULER_SIZE}px 1fr`,
            minWidth: RULER_SIZE + scaledW,
            minHeight: scaledH,
          }}
        >
          <div
            className="sticky left-0 z-10 overflow-hidden border-r border-white/10 bg-loft-surface/95 backdrop-blur-sm"
            style={{ height: scaledH, width: RULER_SIZE }}
          >
            <RulerMarks length={CANVAS_HEIGHT} scale={scale} axis="y" />
          </div>

          <div className="flex items-start justify-start p-6">
            <CanvasPreview scale={scale} softbox={softbox} />
          </div>
        </div>
      </div>
    </section>
  )
}

export { EditorCanvasStage }
