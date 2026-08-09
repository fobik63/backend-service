"use client"

import { Eye, Images, Sparkles, Wrench } from "lucide-react"
import { useEffect, useState } from "react"

import { EyeOfGodSection } from "@/components/editor/eye-of-god-section"
import { ProductParserSection } from "@/components/editor/product-parser-section"
import { PromptBar } from "@/components/editor/prompt-bar"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  MAX_PACK_SIZE,
  MIN_PACK_SIZE,
  PRESET_PACK_SIZES,
  clampPackSize,
} from "@/lib/export/card-pack"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type EditorAiPanelProps = {
  projectTitle?: string
}

type AiStudioTab = "generate" | "parser" | "eye"

function PackParamsSection() {
  const { t } = useI18n()
  const packSize = useEditorStore((s) => s.packSize)
  const setPackSize = useEditorStore((s) => s.setPackSize)
  const isPreset = PRESET_PACK_SIZES.includes(packSize)
  const [customMode, setCustomMode] = useState(!isPreset)
  const [customDraft, setCustomDraft] = useState(String(packSize))
  const [pendingReduce, setPendingReduce] = useState<{
    next: number
    asPreset: boolean
  } | null>(null)
  const customSelected = customMode || !isPreset

  const applySize = (size: number, asPreset = false): "applied" | "pending" => {
    const next = clampPackSize(size)
    if (next < packSize) {
      setPendingReduce({ next, asPreset })
      return "pending"
    }
    setPackSize(next)
    return "applied"
  }

  const selectPreset = (size: number) => {
    if (applySize(size, true) === "pending") return
    setCustomMode(false)
    setCustomDraft(String(size))
  }

  const applyCustom = (raw: string) => {
    setCustomDraft(raw)
    const parsed = Number.parseInt(raw, 10)
    if (!Number.isFinite(parsed)) return
    const next = clampPackSize(parsed)
    if (next >= packSize) {
      setPackSize(next)
    }
  }

  const confirmReduce = () => {
    if (!pendingReduce) return
    const { next, asPreset } = pendingReduce
    setPackSize(next)
    if (asPreset) setCustomMode(false)
    setCustomDraft(String(next))
    setPendingReduce(null)
  }

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Images className="size-4 text-emerald" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.packGeneration")}
        </h3>
      </div>

      <div className="space-y-1.5">
        <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {t("export.packSize")}
        </span>
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-label={t("export.packSize")}
        >
          {PRESET_PACK_SIZES.map((size) => (
            <button
              key={size}
              type="button"
              onClick={() => selectPreset(size)}
              className={cn(
                "inline-flex h-8 min-w-8 flex-1 items-center justify-center rounded-md border text-xs font-medium transition-colors",
                !customSelected && packSize === size
                  ? "border-white/25 bg-white/10 text-foreground"
                  : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={!customSelected && packSize === size}
            >
              {size}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setCustomMode(true)
              if (PRESET_PACK_SIZES.includes(packSize)) {
                setCustomDraft("6")
                setPackSize(6)
              }
            }}
            className={cn(
              "inline-flex h-8 min-w-10 flex-[1.2] items-center justify-center rounded-md border px-2 text-[11px] font-medium transition-colors",
              customSelected
                ? "border-white/25 bg-white/10 text-foreground"
                : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground",
            )}
            aria-pressed={customSelected}
          >
            {t("export.packCustom")}
          </button>
        </div>

        {customSelected ? (
          <div className="flex items-center gap-2 pt-0.5">
            <Input
              type="number"
              min={MIN_PACK_SIZE}
              max={MAX_PACK_SIZE}
              value={customDraft}
              placeholder={t("export.packCustomPlaceholder")}
              aria-label={t("export.packCustom")}
              onChange={(e) => applyCustom(e.target.value)}
              onBlur={() => {
                const next =
                  clampPackSize(Number.parseInt(customDraft, 10) || 1)
                if (applySize(next) === "applied") {
                  setCustomDraft(String(next))
                }
              }}
              className="h-8 border-white/10 bg-white/[0.04] text-xs"
            />
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {MIN_PACK_SIZE}–{MAX_PACK_SIZE}
            </span>
          </div>
        ) : null}

        <p className="text-[10px] text-muted-foreground">
          {t("export.packPhotos", { count: String(packSize) })}
        </p>
      </div>

      <ConfirmDialog
        open={pendingReduce != null}
        onOpenChange={(open) => {
          if (!open) setPendingReduce(null)
        }}
        title={t("editor.packReduceTitle")}
        description={
          pendingReduce
            ? t("editor.packReduceDescription", {
                from: String(packSize),
                to: String(pendingReduce.next),
              })
            : undefined
        }
        cancelLabel={t("editor.packReduceKeep")}
        confirmLabel={t("editor.packReduceDelete")}
        onCancel={() => setCustomDraft(String(packSize))}
        onConfirm={confirmReduce}
      />
    </section>
  )
}

const TAB_ITEMS: {
  id: AiStudioTab
  icon: typeof Sparkles
  labelKey: "editor.aiTabGenerate" | "editor.aiTabParser" | "editor.eyeTab"
  accent?: string
}[] = [
  { id: "generate", icon: Sparkles, labelKey: "editor.aiTabGenerate" },
  { id: "parser", icon: Wrench, labelKey: "editor.aiTabParser" },
  { id: "eye", icon: Eye, labelKey: "editor.eyeTab", accent: "text-amber" },
]

function EditorAiBody({ projectTitle }: EditorAiPanelProps) {
  const { t } = useI18n()
  const [tab, setTab] = useState<AiStudioTab>("generate")

  useEffect(() => {
    const onFocusGenerate = () => setTab("generate")
    window.addEventListener("editor:focus-generate-tab", onFocusGenerate)
    return () =>
      window.removeEventListener("editor:focus-generate-tab", onFocusGenerate)
  }, [])

  return (
    <>
      <div className="shrink-0 space-y-3 border-b border-white/8 px-3 py-3">
        <div>
          <h2 className="font-heading text-sm font-semibold tracking-tight">
            {t("editor.aiPanel")}
          </h2>
          <p className="text-[11px] text-muted-foreground">
            {t("editor.aiPanelHint")}
          </p>
        </div>

        <div
          role="tablist"
          aria-label={t("editor.aiPanelTabs")}
          className="grid grid-cols-3 gap-1 rounded-2xl border border-white/12 bg-gradient-to-b from-white/[0.07] to-white/[0.02] p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
        >
          {TAB_ITEMS.map(({ id, icon: Icon, labelKey, accent }) => {
            const selected = tab === id
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={selected}
                title={t(labelKey)}
                onClick={() => setTab(id)}
                className={cn(
                  "flex min-h-[3.25rem] flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5 text-center transition-all",
                  selected
                    ? "bg-loft-surface text-foreground shadow-sm ring-1 ring-white/15"
                    : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
                )}
              >
                <Icon
                  className={cn(
                    "size-3.5 shrink-0",
                    selected && accent ? accent : undefined,
                  )}
                  aria-hidden
                />
                <span className="line-clamp-2 text-[10px] leading-tight font-medium">
                  {t(labelKey)}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-3 py-3">
        {/* Keep PromptBar mounted so seed-prompt events apply from other tabs. */}
        <div className={cn(tab !== "generate" && "hidden")}>
          <PromptBar variant="panel" projectTitle={projectTitle} />
          <div className="mt-4 border-t border-white/8 pt-3">
            <PackParamsSection />
          </div>
        </div>
        {tab === "parser" ? <ProductParserSection /> : null}
        {tab === "eye" ? <EyeOfGodSection /> : null}
      </div>
    </>
  )
}

const PANEL_SHELL =
  "flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/80 backdrop-blur-xl"

function EditorAiPanel({ projectTitle }: EditorAiPanelProps) {
  const { t } = useI18n()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      <aside
        className={cn(
          "hidden w-[min(100%,360px)] shrink-0 self-stretch lg:flex",
          "lg:w-[clamp(20rem,22vw,22.5rem)]",
          PANEL_SHELL,
        )}
        aria-label={t("editor.aiPanel")}
      >
        <EditorAiBody projectTitle={projectTitle} />
      </aside>

      <div className="pointer-events-none absolute bottom-[9.75rem] left-3 z-20 sm:bottom-[10.25rem] lg:hidden">
        <Button
          type="button"
          size="sm"
          className="pointer-events-auto gap-2 rounded-lg border border-white/15 bg-loft-surface shadow-panel"
          onClick={() => setMobileOpen(true)}
        >
          <Sparkles className="size-4" aria-hidden />
          {t("editor.aiPanel")}
        </Button>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent
            side="left"
            className="flex h-full min-h-0 w-full max-w-[min(100%,24rem)] flex-col border-r border-zinc-800 bg-zinc-900/90 p-0 backdrop-blur-xl"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{t("editor.aiPanel")}</SheetTitle>
              <SheetDescription>{t("editor.aiPanelHint")}</SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <EditorAiBody projectTitle={projectTitle} />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  )
}

export { EditorAiPanel }
export type { EditorAiPanelProps }
