"use client"

import {
  CircleCheck,
  Droplets,
  FlaskConical,
  Leaf,
  Package,
  Palette,
  Plus,
  Shield,
  Sparkles,
  SquareStack,
  Star,
  type LucideIcon,
} from "lucide-react"
import { useEffect, useRef, useState, type FormEvent } from "react"
import { toast } from "sonner"

import { SliderControl } from "@/components/editor/slider-control"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  BADGE_PRESETS,
  FEATURE_CHIP_ICONS,
} from "@/lib/constants/mock-editor"
import {
  addCustomBadge,
  addQuickBadgeById,
} from "@/lib/editor/canvas-actions"
import {
  applyBadgeStylePreset,
  BADGE_STYLE_PRESETS,
  type BadgeStylePresetId,
} from "@/lib/editor/badge-styles"
import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import {
  applyChipLiveColors,
  flushChipLiveIcon,
  setChipAppearanceScrubbing,
} from "@/lib/editor/chip-live"
import { contrastTextForBg } from "@/lib/editor/extract-bg-colors"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import type { FeatureChipDraft } from "@/types/canvas"
import { cn } from "@/lib/utils"

const CHIP_ICON_MAP: Record<string, LucideIcon> = {
  icon_check: CircleCheck,
  icon_drop: Droplets,
  icon_leaf: Leaf,
  icon_shield: Shield,
  icon_star: Star,
  icon_spark: Sparkles,
  icon_box: Package,
  icon_flask: FlaskConical,
}

const TEXT_COLOR_PRESETS = [
  "#FFFFFF",
  "#0F1115",
  "#D4A574",
  "#059669",
  "#F59E0B",
] as const

function contrastTextColor(bg: string): string {
  return contrastTextForBg(bg)
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function toColorInputValue(value: string): string {
  if (value.startsWith("#") && value.length >= 7) return value.slice(0, 7)
  return "#0F1115"
}

function ColorSwatchRow({
  label,
  value,
  presets,
  disabled,
  onChange,
  onCommit,
}: {
  label: string
  value: string
  presets: readonly string[]
  disabled?: boolean
  onChange: (hex: string) => void
  /** Fires when the OS color picker closes / loses focus. */
  onCommit?: () => void
}) {
  const [live, setLive] = useState(value)
  const pickingRef = useRef(false)

  useEffect(() => {
    if (!pickingRef.current) setLive(value)
  }, [value])

  const current = live.toLowerCase()
  const pickerValue = toColorInputValue(live)
  const isCustom = !presets.some((hex) => hex.toLowerCase() === current)

  const pushLive = (hex: string) => {
    setLive(hex)
    onChange(hex)
  }

  return (
    <div className="space-y-1.5">
      <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {presets.map((hex) => {
          const selected = current === hex.toLowerCase()
          return (
            <button
              key={hex}
              type="button"
              title={hex}
              disabled={disabled}
              onClick={() => {
                pickingRef.current = false
                pushLive(hex)
                onCommit?.()
              }}
              className={cn(
                "badge-element is-scale-hover size-7 rounded-md ring-1 ring-white/15 transition-transform disabled:pointer-events-none disabled:opacity-40",
                selected && "ring-2 ring-emerald"
              )}
              style={{ backgroundColor: hex }}
            >
              <span className="sr-only">{hex}</span>
            </button>
          )
        })}
        <label
          title={pickerValue}
          className={cn(
            "badge-element relative flex size-7 items-center justify-center overflow-hidden rounded-md ring-1 ring-white/15 transition-transform",
            disabled
              ? "pointer-events-none opacity-40"
              : "is-scale-hover cursor-pointer",
            isCustom && "ring-2 ring-emerald"
          )}
        >
          <span
            className="absolute inset-0"
            style={{
              background:
                "conic-gradient(from 0deg, #ff0000, #ffea00, #00ff6a, #00e5ff, #0033ff, #cc00ff, #ff0000)",
            }}
            aria-hidden
          />
          <span
            className="absolute inset-[3px] rounded-[4px] shadow-[inset_0_0_0_1px_rgba(0,0,0,0.35)]"
            style={{ backgroundColor: pickerValue }}
            aria-hidden
          />
          <Palette
            className="relative size-3.5 drop-shadow-[0_1px_1px_rgba(0,0,0,0.65)]"
            style={{
              color:
                contrastTextColor(pickerValue) === "#FFFFFF"
                  ? "#FFFFFF"
                  : "#0F1115",
            }}
            aria-hidden
          />
          <input
            type="color"
            value={pickerValue}
            disabled={disabled}
            onInput={(e) => {
              pickingRef.current = true
              pushLive((e.target as HTMLInputElement).value)
            }}
            onChange={(e) => {
              pickingRef.current = true
              pushLive(e.target.value)
            }}
            onBlur={() => {
              pickingRef.current = false
              onCommit?.()
            }}
            className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            aria-label={`${label} — произвольный цвет`}
          />
        </label>
      </div>
    </div>
  )
}

function BadgeToolbarMenu() {
  const [customLabel, setCustomLabel] = useState("")

  const submitCustom = (e?: FormEvent) => {
    e?.preventDefault()
    const result = addCustomBadge(customLabel)
    if (!result) {
      toast.error("Введите текст плашки")
      return
    }
    if (result.created) {
      toast.success(`«${result.label}» на холсте`)
      setCustomLabel("")
    } else {
      toast.message(`«${result.label}» уже на холсте`)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/12 bg-loft-surface/95 px-2.5 text-sm shadow-lg backdrop-blur-sm",
          "text-secondary-foreground outline-none transition-colors hover:bg-secondary/80",
          "focus-visible:ring-2 focus-visible:ring-ring/50"
        )}
      >
        <SquareStack className="size-3.5" aria-hidden />
        Плашка
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Своя плашка</DropdownMenuLabel>
          <form
            className="flex items-center gap-1.5 px-2 pb-2"
            onSubmit={submitCustom}
            onKeyDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <Input
              value={customLabel}
              maxLength={48}
              placeholder="Текст плашки…"
              aria-label="Текст своей плашки"
              className="h-8 border-white/10 bg-white/[0.04] text-xs"
              onChange={(e) => setCustomLabel(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
            />
            <Button
              type="submit"
              size="sm"
              className="h-8 shrink-0 gap-1 px-2"
              disabled={!customLabel.trim()}
            >
              <Plus className="size-3.5" aria-hidden />
              OK
            </Button>
          </form>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Шаблоны</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {BADGE_PRESETS.map((badge) => {
            const Icon = CHIP_ICON_MAP[badge.iconId] ?? Sparkles
            return (
              <DropdownMenuItem
                key={badge.id}
                onClick={() => {
                  const result = addQuickBadgeById(badge.id)
                  if (!result) return
                  if (result.created) {
                    toast.success(`«${result.label}» на холсте`)
                  } else {
                    toast.message(`«${result.label}» уже на холсте`)
                  }
                }}
              >
                <Icon className="size-3.5" aria-hidden />
                {badge.label}
              </DropdownMenuItem>
            )
          })}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function BadgeParamsSection() {
  const { t } = useI18n()
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const toolsPanelFocus = useEditorStore((s) => s.toolsPanelFocus)
  const chipBgPresets = useEditorStore((s) => s.chipBgPresets)
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const beginHistoryTransaction = useEditorStore(
    (s) => s.beginHistoryTransaction
  )
  const commitHistoryTransaction = useEditorStore(
    (s) => s.commitHistoryTransaction
  )
  const layer = layers.find((l) => l.id === selectedLayerId)
  const chip = layer?.chip
  const isBadge = Boolean(chip)
  const disabled = !isBadge || Boolean(layer?.locked)
  const labelInputRef = useRef<HTMLInputElement>(null)
  const subtitleInputRef = useRef<HTMLInputElement>(null)
  /** Local drafts keep caret stable — store updates must not remount/reset the input. */
  const [labelDraft, setLabelDraft] = useState(chip?.label ?? "")
  const [subtitleDraft, setSubtitleDraft] = useState(chip?.subtitle ?? "")

  const storeBlur = chip?.blur ?? (chip?.variant === "glass" ? 12 : 0)
  const storeTextColor =
    chip?.textColor ??
    (chip ? contrastTextColor(chip.bgColor) : "#FFFFFF")
  const storeBg = chip?.bgColor ?? "#0F1115"
  const storeOpacityPct = Math.round((layer?.opacity ?? 1) * 100)

  const [bgDraft, setBgDraft] = useState(storeBg)
  const [textDraft, setTextDraft] = useState(storeTextColor)
  const [blurDraft, setBlurDraft] = useState(storeBlur)
  const [opacityDraft, setOpacityDraft] = useState(storeOpacityPct)

  const scrubbingRef = useRef(false)
  const chipDraftRef = useRef<FeatureChipDraft | null>(chip ?? null)
  const uiRafRef = useRef(0)
  const opacityDraftRef = useRef(storeOpacityPct)

  // Sync drafts from store when selection changes or when not scrubbing.
  useEffect(() => {
    if (!chip) {
      setLabelDraft("")
      setSubtitleDraft("")
      chipDraftRef.current = null
      return
    }
    chipDraftRef.current = chip
    const labelFocused =
      typeof document !== "undefined" &&
      document.activeElement === labelInputRef.current
    const subtitleFocused =
      typeof document !== "undefined" &&
      document.activeElement === subtitleInputRef.current
    if (!labelFocused) setLabelDraft(chip.label)
    if (!subtitleFocused) setSubtitleDraft(chip.subtitle ?? "")
    if (!scrubbingRef.current) {
      setBgDraft(chip.bgColor)
      setTextDraft(chip.textColor ?? contrastTextColor(chip.bgColor))
      setBlurDraft(chip.blur ?? (chip.variant === "glass" ? 12 : 0))
      const op = Math.round((layer?.opacity ?? 1) * 100)
      setOpacityDraft(op)
      opacityDraftRef.current = op
    }
  }, [selectedLayerId, chip, layer?.opacity])

  useEffect(() => {
    return () => {
      if (uiRafRef.current) {
        cancelAnimationFrame(uiRafRef.current)
        uiRafRef.current = 0
      }
      if (scrubbingRef.current) {
        scrubbingRef.current = false
        setChipAppearanceScrubbing(false)
        useEditorStore.getState().commitHistoryTransaction()
      }
    }
  }, [])

  // Focus/select only when toolsPanelFocus nonce fires — never on every chip keystroke.
  useEffect(() => {
    if (!toolsPanelFocus || toolsPanelFocus.field !== "badgeLabel") return
    if (!isBadge || disabled) return

    const tryFocus = () => {
      const input = labelInputRef.current
      // Skip the CSS-hidden desktop clone while the mobile Sheet is used.
      if (!input || input.getClientRects().length === 0) return false
      input.focus()
      input.select()
      input.scrollIntoView({ block: "nearest", behavior: "smooth" })
      return true
    }

    if (tryFocus()) return
    const timers = [50, 150, 300].map((ms) => window.setTimeout(tryFocus, ms))
    return () => {
      for (const id of timers) window.clearTimeout(id)
    }
  }, [toolsPanelFocus, disabled, isBadge, selectedLayerId])

  const beginScrub = () => {
    if (scrubbingRef.current) return
    scrubbingRef.current = true
    setChipAppearanceScrubbing(true)
    beginHistoryTransaction()
  }

  const syncUiDraftsFromRef = () => {
    const live = chipDraftRef.current
    if (!live) return
    setBgDraft(live.bgColor)
    setTextDraft(live.textColor ?? contrastTextColor(live.bgColor))
    setBlurDraft(live.blur ?? (live.variant === "glass" ? 12 : 0))
    setOpacityDraft(opacityDraftRef.current)
  }

  const endScrub = () => {
    if (!scrubbingRef.current) return
    if (uiRafRef.current) {
      cancelAnimationFrame(uiRafRef.current)
      uiRafRef.current = 0
    }
    const live = chipDraftRef.current
    if (layer && live) {
      // Single store write at the end of the drag — keeps scrub at ~60fps.
      updateLayer(layer.id, {
        chip: live,
        opacity: opacityDraftRef.current / 100,
      })
      flushChipLiveIcon(layer.id, live)
      syncUiDraftsFromRef()
    }
    scrubbingRef.current = false
    setChipAppearanceScrubbing(false)
    commitHistoryTransaction()
  }

  const patchChip = (patch: Partial<FeatureChipDraft>) => {
    if (!layer?.chip) return
    const base = chipDraftRef.current ?? layer.chip
    const next = { ...base, ...patch }
    chipDraftRef.current = next
    updateLayer(layer.id, {
      chip: next,
      name:
        patch.label !== undefined
          ? `${t("editor.badge")} «${patch.label || layer.chip.label}»`
          : layer.name,
    })
  }

  const scheduleUiDraft = () => {
    if (uiRafRef.current) return
    uiRafRef.current = requestAnimationFrame(() => {
      uiRafRef.current = 0
      syncUiDraftsFromRef()
    })
  }

  /**
   * Fabric-only during drag. No parent setState / Zustand — keeps scrub at ~60fps.
   * ColorSwatchRow keeps its own live swatch; sidebar drafts sync on commit.
   */
  const scrubChipAppearance = (patch: Partial<FeatureChipDraft>) => {
    if (!layer?.chip) return
    beginScrub()
    const base = chipDraftRef.current ?? layer.chip
    const next = { ...base, ...patch }
    chipDraftRef.current = next
    // Blur slider is controlled by parent state — refresh at most once/frame.
    if (patch.blur !== undefined) scheduleUiDraft()
    applyChipLiveColors(layer.id, next)
  }

  const scrubOpacity = (pct: number) => {
    if (!layer) return
    beginScrub()
    const next = clamp(pct, 10, 100)
    opacityDraftRef.current = next
    scheduleUiDraft()
    const canvas = getActiveFabricCanvas()
    const obj = canvas
      ?.getObjects()
      .find((o) => (o as { layerId?: string }).layerId === layer.id)
    if (obj) {
      obj.set("opacity", next / 100)
      canvas?.requestRenderAll()
    }
  }

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SquareStack className="size-4 text-emerald" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            {t("editor.badge")}
          </h3>
        </div>
        <BadgeToolbarMenu />
      </div>

      {!isBadge ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.badgeSelectHint")}
        </p>
      ) : null}

      <div className={cn("space-y-2.5", !isBadge && "opacity-45")}>
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.badgeText")}
          </span>
          <Input
            ref={labelInputRef}
            value={labelDraft}
            disabled={disabled}
            maxLength={48}
            placeholder={t("editor.badgeTextPlaceholder")}
            onChange={(e) => {
              const next = e.target.value
              setLabelDraft(next)
              patchChip({ label: next })
            }}
            onKeyDown={(e) => e.stopPropagation()}
            className="h-8 border-white/10 bg-white/[0.04] text-xs"
          />
        </div>

        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.badgeSubtitle")}
          </span>
          <Input
            ref={subtitleInputRef}
            value={subtitleDraft}
            disabled={disabled}
            maxLength={64}
            placeholder={t("editor.badgeSubtitlePlaceholder")}
            onChange={(e) => {
              const next = e.target.value
              setSubtitleDraft(next)
              patchChip({ subtitle: next || undefined })
            }}
            onKeyDown={(e) => e.stopPropagation()}
            className="h-8 border-white/10 bg-white/[0.04] text-xs"
          />
        </div>

        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.badgeStyles")}
          </span>
          <div className="grid grid-cols-2 gap-1.5">
            {BADGE_STYLE_PRESETS.map((preset) => {
              const selected = chip?.variant === preset.variant
              return (
                <button
                  key={preset.id}
                  type="button"
                  disabled={disabled}
                  title={preset.label}
                  onClick={() => {
                    if (!layer?.chip) return
                    const next = applyBadgeStylePreset(
                      chipDraftRef.current ?? layer.chip,
                      preset.id as BadgeStylePresetId,
                      {
                        accentColor:
                          preset.id === "solidAccent" ||
                          preset.id === "bordered"
                            ? layer.chip.bgColor.startsWith("#")
                              ? layer.chip.bgColor
                              : undefined
                            : undefined,
                      }
                    )
                    chipDraftRef.current = next
                    setBgDraft(next.bgColor)
                    setTextDraft(
                      next.textColor ?? contrastTextColor(next.bgColor)
                    )
                    setBlurDraft(next.blur ?? 0)
                    updateLayer(layer.id, { chip: next })
                    applyChipLiveColors(layer.id, next, { immediate: true })
                    flushChipLiveIcon(layer.id, next)
                  }}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-left text-[10px] leading-tight transition-colors disabled:pointer-events-none",
                    selected
                      ? "border-emerald/40 bg-emerald/15 text-foreground"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground hover:border-white/20 hover:text-foreground"
                  )}
                >
                  <span className="block font-medium text-foreground/90">
                    {preset.label}
                  </span>
                  <span className="mt-0.5 block text-[9px] opacity-70">
                    {t(`editor.badgeStyleHint.${preset.id}`)}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        <ColorSwatchRow
          label={t("editor.badgeBgColor")}
          value={bgDraft}
          presets={chipBgPresets}
          disabled={disabled}
          onChange={(bgColor) =>
            scrubChipAppearance({
              bgColor,
              variant:
                blurDraft > 0
                  ? "glass"
                  : chip?.variant === "bordered" || chip?.variant === "dark"
                    ? chip.variant
                    : "solid",
            })
          }
          onCommit={endScrub}
        />

        <ColorSwatchRow
          label={t("editor.badgeTextColor")}
          value={textDraft}
          presets={TEXT_COLOR_PRESETS}
          disabled={disabled}
          onChange={(next) => scrubChipAppearance({ textColor: next })}
          onCommit={endScrub}
        />

        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.badgeIcon")}
          </span>
          <div className="grid grid-cols-4 gap-1.5">
            {FEATURE_CHIP_ICONS.map((icon) => {
              const Icon = CHIP_ICON_MAP[icon.id] ?? Sparkles
              const selected = chip?.iconId === icon.id
              return (
                <button
                  key={icon.id}
                  type="button"
                  title={icon.label}
                  disabled={disabled}
                  onClick={() => patchChip({ iconId: icon.id })}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border px-1.5 py-2 text-[9px] transition-colors disabled:pointer-events-none",
                    selected
                      ? "border-emerald/40 bg-emerald/15 text-foreground"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground hover:border-white/20 hover:text-foreground"
                  )}
                >
                  <Icon className="size-4 text-copper" aria-hidden />
                  {icon.label}
                </button>
              )
            })}
          </div>
        </div>

        <SliderControl
          label={t("editor.opacity")}
          value={opacityDraft}
          min={10}
          max={100}
          unit="%"
          disabled={disabled}
          onChange={scrubOpacity}
          onValueCommitted={endScrub}
        />

        <SliderControl
          label={t("editor.blur")}
          value={blurDraft}
          min={0}
          max={32}
          unit="px"
          disabled={disabled}
          onChange={(blur) => {
            const next = clamp(blur, 0, 32)
            scrubChipAppearance({
              blur: next,
              variant: next > 0 ? "glass" : "solid",
            })
          }}
          onValueCommitted={endScrub}
          hint={<span>{t("editor.badgeGlassHint")}</span>}
        />
      </div>
    </section>
  )
}

export { BadgeToolbarMenu, BadgeParamsSection, CHIP_ICON_MAP }
