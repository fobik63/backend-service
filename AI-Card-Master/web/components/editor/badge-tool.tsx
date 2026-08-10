"use client"

import {
  CircleCheck,
  Droplets,
  FlaskConical,
  Leaf,
  Package,
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
  FEATURE_CHIP_BG_PRESETS,
  FEATURE_CHIP_ICONS,
} from "@/lib/constants/mock-editor"
import {
  addCustomBadge,
  addQuickBadgeById,
} from "@/lib/editor/canvas-actions"
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
  const hex = bg.toLowerCase()
  if (
    hex === "#ffffff" ||
    hex === "#fff" ||
    hex === "#f59e0b" ||
    hex.startsWith("rgba")
  ) {
    return hex.startsWith("rgba") ? "#FFFFFF" : "#0F1115"
  }
  return "#FFFFFF"
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
}: {
  label: string
  value: string
  presets: readonly string[]
  disabled?: boolean
  onChange: (hex: string) => void
}) {
  const current = value.toLowerCase()

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
              onClick={() => onChange(hex)}
              className={cn(
                "size-7 rounded-md ring-1 ring-white/15 transition-transform hover:scale-105 disabled:pointer-events-none disabled:opacity-40",
                selected && "ring-2 ring-emerald"
              )}
              style={{ backgroundColor: hex }}
            >
              <span className="sr-only">{hex}</span>
            </button>
          )
        })}
        <label
          className={cn(
            "relative size-7 overflow-hidden rounded-md ring-1 ring-white/15",
            disabled ? "pointer-events-none opacity-40" : "cursor-pointer"
          )}
        >
          <span
            className="absolute inset-0"
            style={{ backgroundColor: toColorInputValue(value) }}
            aria-hidden
          />
          <input
            type="color"
            value={toColorInputValue(value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            aria-label={label}
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
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const layer = layers.find((l) => l.id === selectedLayerId)
  const chip = layer?.chip
  const isBadge = Boolean(chip)
  const disabled = !isBadge || Boolean(layer?.locked)
  const labelInputRef = useRef<HTMLInputElement>(null)
  const subtitleInputRef = useRef<HTMLInputElement>(null)
  /** Local drafts keep caret stable — store updates must not remount/reset the input. */
  const [labelDraft, setLabelDraft] = useState(chip?.label ?? "")
  const [subtitleDraft, setSubtitleDraft] = useState(chip?.subtitle ?? "")

  // Sync drafts from store when selection changes or when inputs are not focused.
  useEffect(() => {
    if (!chip) {
      setLabelDraft("")
      setSubtitleDraft("")
      return
    }
    const labelFocused =
      typeof document !== "undefined" &&
      document.activeElement === labelInputRef.current
    const subtitleFocused =
      typeof document !== "undefined" &&
      document.activeElement === subtitleInputRef.current
    if (!labelFocused) setLabelDraft(chip.label)
    if (!subtitleFocused) setSubtitleDraft(chip.subtitle ?? "")
  }, [selectedLayerId, chip])

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

  const patchChip = (patch: Partial<FeatureChipDraft>) => {
    if (!layer?.chip) return
    updateLayer(layer.id, {
      chip: { ...layer.chip, ...patch },
      name:
        patch.label !== undefined
          ? `${t("editor.badge")} «${patch.label || layer.chip.label}»`
          : layer.name,
    })
  }

  const blurValue = chip?.blur ?? (chip?.variant === "glass" ? 12 : 0)
  const textColor =
    chip?.textColor ??
    (chip ? contrastTextColor(chip.bgColor) : "#FFFFFF")
  const opacityPct = Math.round((layer?.opacity ?? 1) * 100)

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
            className="h-8 border-white/10 bg-white/[0.04] text-xs"
          />
        </div>

        <ColorSwatchRow
          label={t("editor.badgeBgColor")}
          value={chip?.bgColor ?? "#0F1115"}
          presets={FEATURE_CHIP_BG_PRESETS}
          disabled={disabled}
          onChange={(bgColor) =>
            patchChip({
              bgColor,
              variant: blurValue > 0 ? "glass" : "solid",
            })
          }
        />

        <ColorSwatchRow
          label={t("editor.badgeTextColor")}
          value={textColor}
          presets={TEXT_COLOR_PRESETS}
          disabled={disabled}
          onChange={(next) => patchChip({ textColor: next })}
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
          value={opacityPct}
          min={10}
          max={100}
          unit="%"
          disabled={disabled}
          onChange={(pct) => {
            if (!layer) return
            updateLayer(layer.id, {
              opacity: clamp(pct, 10, 100) / 100,
            })
          }}
        />

        <SliderControl
          label={t("editor.blur")}
          value={blurValue}
          min={0}
          max={32}
          unit="px"
          disabled={disabled}
          onChange={(blur) => {
            const next = clamp(blur, 0, 32)
            patchChip({
              blur: next,
              variant: next > 0 ? "glass" : "solid",
            })
          }}
          hint={<span>{t("editor.badgeGlassHint")}</span>}
        />
      </div>
    </section>
  )
}

export { BadgeToolbarMenu, BadgeParamsSection, CHIP_ICON_MAP }
