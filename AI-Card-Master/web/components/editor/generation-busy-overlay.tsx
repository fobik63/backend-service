"use client"

import { Sparkles } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type GenerationBusyOverlayProps = {
  kind: "generating" | "removing-bg" | "loading-image"
  /** 0–100 for determinate progress; null shows indeterminate shimmer. */
  progress: number | null
  className?: string
}

const LABELS: Record<GenerationBusyOverlayProps["kind"], string> = {
  generating: "Генерация карточки…",
  "removing-bg": "Вырезаем фон…",
  "loading-image": "Загрузка изображения…",
}

const HINTS: Record<GenerationBusyOverlayProps["kind"], string> = {
  generating: "Собираем композицию, плашки и SEO-текст",
  "removing-bg": "Изолируем товар на прозрачном фоне",
  "loading-image": "Подготавливаем превью товара",
}

function GenerationBusyOverlay({
  kind,
  progress,
  className,
}: GenerationBusyOverlayProps) {
  const determinate =
    typeof progress === "number" && Number.isFinite(progress)
  const pct = determinate ? Math.min(100, Math.max(0, progress)) : 0

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 z-[200] flex flex-col items-center justify-center gap-4 bg-loft/80 px-6",
        className,
      )}
      data-export-chrome="true"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="w-[min(56%,220px)] overflow-hidden rounded-xl border border-white/10 bg-loft-surface p-3 shadow-panel">
        <Skeleton className="aspect-[3/4] w-full rounded-lg" />
        <div className="mt-3 space-y-2">
          <Skeleton className="h-3 w-[78%] rounded" />
          <Skeleton className="h-2.5 w-[52%] rounded" />
          <div className="flex gap-1.5 pt-1">
            <Skeleton className="h-5 w-14 rounded" />
            <Skeleton className="h-5 w-16 rounded" />
            <Skeleton className="h-5 w-12 rounded" />
          </div>
        </div>
      </div>

      <div className="flex w-full max-w-[240px] flex-col items-center gap-2 text-center">
        <div className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
          <Sparkles className="size-3.5 text-muted-foreground" aria-hidden />
          {LABELS[kind]}
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {HINTS[kind]}
        </p>

        <div
          className="mt-1 h-1 w-full overflow-hidden rounded-full bg-white/10"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={determinate ? Math.round(pct) : undefined}
          aria-label={LABELS[kind]}
        >
          {determinate ? (
            <div
              className="gpu-anim h-full w-full origin-left rounded-full bg-foreground transition-transform duration-150 ease-out"
              style={{ transform: `translateZ(0) scaleX(${pct / 100})` }}
            />
          ) : (
            <div className="h-full w-1/3 animate-[progress-indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-foreground/80" />
          )}
        </div>
        {determinate ? (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground/80">
            {Math.round(pct)}%
          </span>
        ) : null}
      </div>
    </div>
  )
}

export { GenerationBusyOverlay }
export type { GenerationBusyOverlayProps }
