"use client"

import { Download, Loader2, RotateCw, Undo2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import {
  CanvasPhotoDropzone,
  CanvasToolbar,
} from "@/components/editor/canvas-toolbar"
import { EditorCanvas } from "@/components/editor/canvas"
import { EditorPageStrip } from "@/components/editor/page-strip"
import { ErrorBoundary } from "@/components/error-boundary"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import {
  downloadCurrentCanvasImage,
  findEditorExportCanvas,
} from "@/lib/export/card-pack"
import { getApiErrorMessage } from "@/lib/api"
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

function CanvasQuickBar() {
  const { t } = useI18n()
  const zoomMode = useEditorStore((s) => s.zoomMode)
  const setZoomMode = useEditorStore((s) => s.setZoomMode)
  const canUndo = useEditorStore((s) => s.canUndo)
  const undo = useEditorStore((s) => s.undo)
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const [exporting, setExporting] = useState(false)

  const selected = layers.find((l) => l.id === selectedLayerId)
  const canRotate = Boolean(selected && !selected.locked)

  const handleRotate = () => {
    if (!selected || selected.locked) return
    const next = ((((selected.rotation ?? 0) + 90) % 360) + 360) % 360
    updateLayer(selected.id, { rotation: next })
  }

  const handleDownload = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const title =
        layers.find((l) => l.type === "text" && l.text?.trim())?.text?.trim() ||
        "card"
      const safe =
        title.replace(/[^\w\-а-яё]+/gi, "-").replace(/^-+|-+$/g, "") || "card"
      await downloadCurrentCanvasImage({
        canvasEl: findEditorExportCanvas(),
        filename: `${safe}-page-${activePageIndex + 1}.png`,
        format: "png",
      })
      toast.success(
        t("editor.downloadCurrentSuccess", {
          n: String(activePageIndex + 1),
          format: "PNG",
        }),
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.downloadCurrentError")))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-white/8 px-3 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-xs text-muted-foreground">
          {t("editor.canvas")}{" "}
          <span className="font-mono text-foreground/80">
            {CANVAS_WIDTH}×{CANVAS_HEIGHT}
          </span>
          <span className="ml-2 text-muted-foreground/80">
            · {t("editor.pageNShort", { n: String(activePageIndex + 1) })}
          </span>
        </p>
      </div>

      <div
        className="flex flex-wrap items-center gap-1.5 sm:justify-end"
        role="toolbar"
        aria-label={t("editor.quickBarAria")}
      >
        <div
          className="inline-flex items-center gap-0.5 rounded-lg border border-white/10 bg-loft-surface p-0.5"
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
                zoomMode === opt.mode && "bg-white/10 text-foreground",
              )}
              onClick={() => setZoomMode(opt.mode)}
            >
              {opt.label}
            </Button>
          ))}
        </div>

        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!canUndo}
          className="h-8 gap-1.5 border border-white/12 bg-loft-surface"
          onClick={undo}
          aria-label={t("editor.undo")}
          title={`${t("editor.undo")} (Ctrl+Z)`}
        >
          <Undo2 className="size-3.5" aria-hidden />
          <span className="hidden sm:inline">{t("editor.undo")}</span>
        </Button>

        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!canRotate}
          className="h-8 gap-1.5 border border-white/12 bg-loft-surface"
          onClick={handleRotate}
          aria-label={t("editor.rotate")}
          title={t("editor.rotate90")}
        >
          <RotateCw className="size-3.5" aria-hidden />
          <span className="hidden sm:inline">{t("editor.rotate")}</span>
        </Button>

        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={exporting}
          aria-busy={exporting}
          className="h-8 gap-1.5 border border-emerald/30 bg-emerald/10 text-emerald hover:bg-emerald/15"
          onClick={() => void handleDownload()}
          aria-label={t("editor.download")}
        >
          {exporting ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Download className="size-3.5" aria-hidden />
          )}
          <span className="hidden sm:inline">{t("editor.downloadShort")}</span>
        </Button>

        <CanvasToolbar className="min-w-0" compact />
      </div>
    </div>
  )
}

function EditorCanvasStage() {
  const { t } = useI18n()
  const zoomMode = useEditorStore((s) => s.zoomMode)
  const softbox = useEditorStore((s) => s.softbox)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)

  const viewportRef = useRef<HTMLDivElement>(null)
  const [fitScale, setFitScale] = useState(0.35)
  const [canvasMountKey, setCanvasMountKey] = useState(0)

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
  const showDropzone =
    !productPreviewUrl &&
    busyKind !== "loading-image" &&
    busyKind !== "generating" &&
    busyKind !== "removing-bg"

  return (
    <section
      className="relative flex h-full min-h-0 min-w-0 flex-1 flex-col self-stretch overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/40"
      aria-label={t("editor.canvasArea")}
    >
      <CanvasQuickBar />

      <div className="relative min-h-0 flex-1">
        <div
          ref={viewportRef}
          className="flex h-full items-center justify-center overflow-auto p-3 sm:p-4"
        >
          <ErrorBoundary
            key={`canvas-boundary-${activePageIndex}-${canvasMountKey}`}
            resetKey={`${activePageIndex}-${canvasMountKey}`}
            title="Ошибка элемента холста"
            description="Один из слоёв не отрисовался. Проект в памяти сохранён — холст можно перезапустить без потери данных."
            className="min-h-[240px] w-full max-w-full"
            onReset={() => setCanvasMountKey((k) => k + 1)}
          >
            <EditorCanvas
              key={`page-${activePageIndex}-${canvasMountKey}`}
              scale={scale}
              softbox={softbox}
            />
          </ErrorBoundary>
        </div>
        {showDropzone ? <CanvasPhotoDropzone /> : null}
      </div>

      <EditorPageStrip />
    </section>
  )
}

export { EditorCanvasStage }
