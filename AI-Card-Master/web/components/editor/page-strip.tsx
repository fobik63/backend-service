"use client"

import { CARD_PACK_SLIDES } from "@/lib/export/card-pack"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

function pageLabel(index: number, locale: "ru" | "en"): string {
  const slide = CARD_PACK_SLIDES[index % CARD_PACK_SLIDES.length]
  if (!slide) return String(index + 1)
  const base = locale === "en" ? slide.titleEn : slide.titleRu
  if (index < CARD_PACK_SLIDES.length) return base
  const cycle = Math.floor(index / CARD_PACK_SLIDES.length) + 1
  return `${base} ${cycle}`
}

function EditorPageStrip({ className }: { className?: string }) {
  const { t, locale } = useI18n()
  const pages = useEditorStore((s) => s.pages)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const setActivePageIndex = useEditorStore((s) => s.setActivePageIndex)
  const packSize = useEditorStore((s) => s.packSize)

  const count = Math.min(pages.length, packSize)

  return (
    <div
      className={cn(
        "shrink-0 border-t border-zinc-800/80 bg-zinc-900/60 px-3 py-2.5 backdrop-blur-xl",
        className
      )}
      role="tablist"
      aria-label={t("editor.pagesAria")}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {t("editor.pages")}
        </p>
        <p className="font-mono text-[10px] text-muted-foreground">
          {activePageIndex + 1}/{count}
        </p>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-0.5">
        {Array.from({ length: count }, (_, index) => {
          const active = index === activePageIndex
          const label = pageLabel(index, locale)
          return (
            <button
              key={`page-${index}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={t("editor.pageN", {
                n: String(index + 1),
                title: label,
              })}
              onClick={() => setActivePageIndex(index)}
              className={cn(
                "group flex w-[72px] shrink-0 flex-col gap-1 rounded-lg border p-1.5 text-left transition-colors",
                active
                  ? "border-white/30 bg-white/[0.06]"
                  : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]"
              )}
            >
              <div
                className={cn(
                  "relative aspect-[3/4] w-full overflow-hidden rounded-md",
                  active ? "ring-1 ring-white/25" : "ring-1 ring-white/8"
                )}
                style={{
                  background:
                    "linear-gradient(155deg,#1a1a1c 0%,#121214 48%,#0a0a0b 100%)",
                }}
              >
                <span
                  className={cn(
                    "absolute inset-x-0 bottom-0 truncate px-1 py-0.5 text-center text-[8px] font-semibold",
                    active
                      ? "bg-foreground text-primary-foreground"
                      : "bg-black/55 text-white/85"
                  )}
                >
                  {index + 1}
                </span>
              </div>
              <span
                className={cn(
                  "truncate text-[10px] leading-tight",
                  active ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {label}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export { EditorPageStrip }
