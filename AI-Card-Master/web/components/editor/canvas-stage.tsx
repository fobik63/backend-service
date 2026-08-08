"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { CanvasToolbar } from "@/components/editor/canvas-toolbar"
import { EditorCanvas } from "@/components/editor/canvas"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import { useI18n } from "@/lib/i18n"
import {
  useEditorStore,
  type EditorZoomMode,
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

function EditorCanvasStage() {
  const { t } = useI18n()
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

  if (!softbox) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center bg-transparent">
        <Skeleton className="h-[min(60vh,520px)] w-[min(45vw,360px)] rounded-xl" />
      </div>
    )
  }

  const scale = resolveZoomScale(zoomMode, fitScale)
  const scaledW = CANVAS_WIDTH * scale
  const scaledH = CANVAS_HEIGHT * scale

  return (
    <section
      className="relative flex min-w-0 flex-1 flex-col bg-transparent"
      aria-label="Область предпросмотра"
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/8 px-4">
        <p className="text-xs text-muted-foreground">
          {t("editor.canvas")}{" "}
          <span className="font-mono text-foreground/80">
            {CANVAS_WIDTH}×{CANVAS_HEIGHT}
          </span>
        </p>
        <div
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-loft-surface/80 p-0.5"
          role="group"
          aria-label={t("editor.zoom")}
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

      <div className="relative min-h-0 flex-1">
        <CanvasToolbar />
        <div ref={viewportRef} className="h-full overflow-auto">
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
              <EditorCanvas scale={scale} softbox={softbox} />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export { EditorCanvasStage }
