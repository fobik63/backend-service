"use client"

import { useEffect, useRef, useState } from "react"

import { CanvasToolbar } from "@/components/editor/canvas-toolbar"
import { EditorCanvas } from "@/components/editor/canvas"
import { EditorPageStrip } from "@/components/editor/page-strip"
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

function EditorCanvasStage() {
  const { t } = useI18n()
  const zoomMode = useEditorStore((s) => s.zoomMode)
  const setZoomMode = useEditorStore((s) => s.setZoomMode)
  const softbox = useEditorStore((s) => s.softbox)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)

  const viewportRef = useRef<HTMLDivElement>(null)
  const [fitScale, setFitScale] = useState(0.35)

  useEffect(() => {
    const el = viewportRef.current
    if (!el) return

    const measure = () => {
      const pad = 24
      const availW = Math.max(120, el.clientWidth - pad)
      const availH = Math.max(120, el.clientHeight - pad)
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
      <div className="flex h-full min-h-0 min-w-0 flex-1 items-center justify-center self-stretch bg-transparent">
        <Skeleton className="h-[min(60vh,520px)] w-[min(45vw,360px)] rounded-xl" />
      </div>
    )
  }

  const scale = resolveZoomScale(zoomMode, fitScale)

  return (
    <section
      className="relative flex h-full min-w-0 flex-1 flex-col self-stretch bg-transparent"
      aria-label={t("editor.canvasArea")}
    >
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-white/8 px-3">
        <p className="text-xs text-muted-foreground">
          {t("editor.canvas")}{" "}
          <span className="font-mono text-foreground/80">
            {CANVAS_WIDTH}×{CANVAS_HEIGHT}
          </span>
          <span className="ml-2 text-muted-foreground/80">
            · {t("editor.pageNShort", { n: String(activePageIndex + 1) })}
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
        <div
          ref={viewportRef}
          className="flex h-full items-center justify-center overflow-auto p-4"
        >
          <EditorCanvas
            key={`page-${activePageIndex}`}
            scale={scale}
            softbox={softbox}
          />
        </div>
      </div>

      <EditorPageStrip />
    </section>
  )
}

export { EditorCanvasStage }
