"use client"

import {
  ChevronDown,
  Eye,
  Images,
  Lamp,
  SlidersHorizontal,
  Type,
  Wrench,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { BadgeParamsSection } from "@/components/editor/badge-tool"
import { EyeOfGodSection } from "@/components/editor/eye-of-god-section"
import { ProductParserSection } from "@/components/editor/product-parser-section"
import { PromptBar } from "@/components/editor/prompt-bar"
import { SliderControl } from "@/components/editor/slider-control"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { useI18n } from "@/lib/i18n"
import {
  MAX_PACK_SIZE,
  MIN_PACK_SIZE,
  PRESET_PACK_SIZES,
  clampPackSize,
} from "@/lib/export/card-pack"
import {
  useEditorStore,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import {
  DEFAULT_TEXT_STYLE,
  EDITOR_FONT_FAMILIES,
  type EditorFontFamily,
  type TextLayerStyle,
} from "@/types/canvas"
import { cn } from "@/lib/utils"

const FONT_CSS: Record<EditorFontFamily, string> = {
  Inter: "var(--font-inter), Inter, sans-serif",
  Montserrat: "var(--font-montserrat), Montserrat, sans-serif",
  Roboto: "var(--font-roboto), Roboto, sans-serif",
  "Space Grotesk": "var(--font-space-grotesk), 'Space Grotesk', sans-serif",
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

type EditorSettingsPanelProps = {
  projectTitle?: string
}

function TextParamsSection() {
  const { t } = useI18n()
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const updateLayer = useEditorStore((s) => s.updateLayer)

  const layer = layers.find((l) => l.id === selectedLayerId)
  const isText = layer?.type === "text"
  const disabled = !isText || Boolean(layer?.locked)
  const style: TextLayerStyle = {
    ...DEFAULT_TEXT_STYLE,
    ...layer?.textStyle,
  }

  const patchStyle = (patch: Partial<TextLayerStyle>) => {
    if (!layer || layer.type !== "text") return
    updateLayer(layer.id, {
      textStyle: { ...style, ...patch },
    })
  }

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Type className="size-4 text-copper" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.text")}
        </h3>
      </div>

      {!isText ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.textSelectHint")}
        </p>
      ) : null}

      <div className={cn("space-y-2.5", !isText && "opacity-45")}>
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.font")}
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={disabled}
              className={cn(
                "inline-flex h-8 w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-xs outline-none",
                "focus-visible:ring-2 focus-visible:ring-ring/50",
                "disabled:pointer-events-none disabled:opacity-50"
              )}
            >
              <span style={{ fontFamily: FONT_CSS[style.fontFamily] }}>
                {style.fontFamily}
              </span>
              <ChevronDown className="size-3.5 opacity-60" aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[var(--anchor-width)]">
              <DropdownMenuRadioGroup
                value={style.fontFamily}
                onValueChange={(v) => {
                  if (EDITOR_FONT_FAMILIES.includes(v as EditorFontFamily)) {
                    patchStyle({ fontFamily: v as EditorFontFamily })
                  }
                }}
              >
                {EDITOR_FONT_FAMILIES.map((font) => (
                  <DropdownMenuRadioItem
                    key={font}
                    value={font}
                    className="text-xs"
                    style={{ fontFamily: FONT_CSS[font] }}
                  >
                    {font}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <SliderControl
          label={t("editor.fontSize")}
          value={style.fontSize}
          min={12}
          max={128}
          unit="px"
          disabled={disabled}
          onChange={(fontSize) =>
            patchStyle({ fontSize: clamp(fontSize, 12, 128) })
          }
        />
      </div>
    </section>
  )
}

function SoftboxParamsSection() {
  const { t } = useI18n()
  const softbox = useEditorStore((s) => s.softbox)
  const setSoftbox = useEditorStore((s) => s.setSoftbox)
  const setSoftboxScrubbing = useEditorStore((s) => s.setSoftboxScrubbing)
  const beginHistoryTransaction = useEditorStore(
    (s) => s.beginHistoryTransaction
  )
  const commitHistoryTransaction = useEditorStore(
    (s) => s.commitHistoryTransaction
  )

  /** Local UI draft — slider labels update immediately without waiting on canvas. */
  const [draft, setDraft] = useState<SoftboxSettings>(softbox)
  const draftRef = useRef(draft)
  const scrubbingRef = useRef(false)
  const rafRef = useRef(0)
  const disabled = !draft.enabled

  useEffect(() => {
    if (scrubbingRef.current) return
    setDraft(softbox)
    draftRef.current = softbox
  }, [softbox])

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      if (scrubbingRef.current) {
        scrubbingRef.current = false
        useEditorStore.getState().setSoftboxScrubbing(false)
        useEditorStore.getState().commitHistoryTransaction()
      }
    }
  }, [])

  const pushDraftToStore = (next: SoftboxSettings) => {
    setSoftbox({
      intensity: next.intensity,
      colorTempK: next.colorTempK,
      lightAngle: next.lightAngle,
      softboxDiffusion: next.softboxDiffusion,
      lightElevation: next.lightElevation,
      enabled: next.enabled,
    })
  }

  const scheduleStoreCommit = () => {
    // Coalesce to one store write per animation frame (16–30ms).
    if (rafRef.current) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      pushDraftToStore(draftRef.current)
    })
  }

  const beginScrub = () => {
    if (scrubbingRef.current) return
    scrubbingRef.current = true
    beginHistoryTransaction()
    setSoftboxScrubbing(true)
  }

  const endScrub = () => {
    if (!scrubbingRef.current) return
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
    pushDraftToStore(draftRef.current)
    scrubbingRef.current = false
    setSoftboxScrubbing(false)
    commitHistoryTransaction()
  }

  const patchDraft = (patch: Partial<SoftboxSettings>) => {
    beginScrub()
    setDraft((prev) => {
      const next = { ...prev, ...patch }
      draftRef.current = next
      scheduleStoreCommit()
      return next
    })
  }

  const tempLabel = (v: number) => {
    if (v <= 4000) return t("editor.colorTempWarm")
    if (v >= 5600) return t("editor.colorTempCold")
    return t("editor.colorTempNeutral")
  }

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Lamp className="size-4 text-amber" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            {t("editor.softboxFull")}
          </h3>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={draft.enabled}
          onClick={() => {
            const enabled = !draft.enabled
            const next = { ...draftRef.current, enabled }
            draftRef.current = next
            setDraft(next)
            beginHistoryTransaction()
            pushDraftToStore(next)
            commitHistoryTransaction()
          }}
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors",
            draft.enabled ? "bg-foreground" : "bg-white/15"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
              draft.enabled && "translate-x-4"
            )}
          />
          <span className="sr-only">{t("editor.softbox")}</span>
        </button>
      </div>

      <div className={cn("space-y-2.5", disabled && "opacity-45")}>
        <SliderControl
          label={t("editor.intensity")}
          value={draft.intensity}
          min={0}
          max={200}
          unit="%"
          disabled={disabled}
          onChange={(intensity) =>
            patchDraft({ intensity: clamp(intensity, 0, 200) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.colorTemp")}
          value={draft.colorTempK}
          min={2700}
          max={6500}
          step={50}
          unit="K"
          disabled={disabled}
          formatValue={(v) => `${v}K ${tempLabel(v)}`}
          onChange={(colorTempK) =>
            patchDraft({ colorTempK: clamp(colorTempK, 2700, 6500) })
          }
          onValueCommitted={endScrub}
          hint={
            <div className="flex justify-between">
              <span>2700 {t("editor.colorTempWarm")}</span>
              <span>6500 {t("editor.colorTempCold")}</span>
            </div>
          }
        />
        <SliderControl
          label={t("editor.angle")}
          value={draft.lightAngle}
          min={0}
          max={360}
          unit="°"
          disabled={disabled}
          onChange={(lightAngle) =>
            patchDraft({
              lightAngle: ((lightAngle % 360) + 360) % 360,
            })
          }
          onValueCommitted={endScrub}
          hint={
            <div className="flex justify-between">
              <span>{t("editor.angleRight")}</span>
              <span>{t("editor.angleLeft")}</span>
            </div>
          }
        />
        <SliderControl
          label={t("editor.diffusion")}
          value={draft.softboxDiffusion}
          min={0}
          max={100}
          unit="%"
          disabled={disabled}
          onChange={(softboxDiffusion) =>
            patchDraft({
              softboxDiffusion: clamp(softboxDiffusion, 0, 100),
            })
          }
          onValueCommitted={endScrub}
        />
      </div>
    </section>
  )
}

function PackParamsSection() {
  const { t } = useI18n()
  const packSize = useEditorStore((s) => s.packSize)
  const setPackSize = useEditorStore((s) => s.setPackSize)
  const isPreset = PRESET_PACK_SIZES.includes(packSize)
  const [customMode, setCustomMode] = useState(!isPreset)
  const [customDraft, setCustomDraft] = useState(String(packSize))
  const customSelected = customMode || !isPreset

  const applySize = (size: number): boolean => {
    const next = clampPackSize(size)
    if (
      next < packSize &&
      !window.confirm(
        `Уменьшить набор с ${packSize} до ${next}? Страницы после ${next}-й будут удалены.`
      )
    ) {
      return false
    }
    setPackSize(next)
    return true
  }

  const selectPreset = (size: number) => {
    if (!applySize(size)) return
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
                  : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground"
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
                : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground"
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
                const next = clampPackSize(Number.parseInt(customDraft, 10) || 1)
                if (applySize(next)) {
                  setCustomDraft(String(next))
                } else {
                  setCustomDraft(String(packSize))
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
    </section>
  )
}

function EditorSettingsBody({ projectTitle }: EditorSettingsPanelProps) {
  const { t } = useI18n()
  const [tab, setTab] = useState<"tools" | "eye">("tools")

  return (
    <>
      <div className="shrink-0 border-b border-white/8 px-3 py-2.5">
        <h2 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.tools")}
        </h2>
        <p className="text-[11px] text-muted-foreground">
          {t("editor.toolsHint")}
        </p>
        <div
          role="tablist"
          aria-label={t("editor.toolsTabs")}
          className="mt-2.5 grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-1"
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab === "tools"}
            onClick={() => setTab("tools")}
            className={cn(
              "inline-flex h-8 items-center justify-center gap-1.5 rounded-md text-[11px] font-medium transition-colors",
              tab === "tools"
                ? "bg-loft-surface text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Wrench className="size-3.5" aria-hidden />
            {t("editor.toolsTab")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "eye"}
            onClick={() => setTab("eye")}
            className={cn(
              "inline-flex h-8 items-center justify-center gap-1.5 rounded-md text-[11px] font-medium transition-colors",
              tab === "eye"
                ? "bg-loft-surface text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Eye className="size-3.5 text-amber" aria-hidden />
            {t("editor.eyeTab")}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-3 py-3">
        {tab === "tools" ? (
          <>
            <ProductParserSection />
            <div className="border-t border-white/8 pt-3">
              <TextParamsSection />
            </div>
            <div className="border-t border-white/8 pt-3">
              <BadgeParamsSection />
            </div>
            <div className="border-t border-white/8 pt-3">
              <SoftboxParamsSection />
            </div>
            <div className="border-t border-white/8 pt-3">
              <PackParamsSection />
            </div>
          </>
        ) : (
          <EyeOfGodSection />
        )}
      </div>

      <div className="shrink-0 border-t border-white/8 bg-[#12151a] px-3 py-3">
        <PromptBar variant="panel" projectTitle={projectTitle} />
      </div>
    </>
  )
}

function EditorSettingsPanel({ projectTitle }: EditorSettingsPanelProps) {
  const { t } = useI18n()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      <aside
        className="hidden h-full w-[min(100%,340px)] shrink-0 flex-col self-stretch overflow-hidden border-l border-zinc-800/80 bg-zinc-900/60 backdrop-blur-xl lg:flex"
        aria-label={t("editor.tools")}
      >
        <EditorSettingsBody projectTitle={projectTitle} />
      </aside>

      {/* Keep FAB above EditorPageStrip on phones. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-[9.75rem] z-20 flex justify-center px-3 sm:bottom-[10.25rem] lg:hidden">
        <Button
          type="button"
          size="sm"
          className="pointer-events-auto gap-2 rounded-lg border border-white/15 bg-loft-surface shadow-panel"
          onClick={() => setMobileOpen(true)}
        >
          <SlidersHorizontal className="size-4" aria-hidden />
          {t("editor.tools")}
        </Button>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent
            side="right"
            className="flex h-full min-h-0 w-full max-w-[min(100%,24rem)] flex-col border-l border-zinc-800/80 bg-zinc-900/60 p-0 backdrop-blur-xl"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{t("editor.tools")}</SheetTitle>
              <SheetDescription>{t("editor.toolsHint")}</SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <EditorSettingsBody projectTitle={projectTitle} />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  )
}

export { EditorSettingsPanel }
export type { EditorSettingsPanelProps }
