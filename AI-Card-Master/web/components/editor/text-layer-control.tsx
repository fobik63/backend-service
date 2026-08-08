"use client"

import {
  Check,
  ChevronDown,
  CircleCheck,
  Droplets,
  FlaskConical,
  Leaf,
  Package,
  Plus,
  Shield,
  Sparkles,
  Star,
  Type,
  type LucideIcon,
} from "lucide-react"
import { useState, type ReactNode } from "react"
import { toast } from "sonner"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import {
  FEATURE_CHIP_BG_PRESETS,
  FEATURE_CHIP_ICONS,
  nextBadgePosition,
} from "@/lib/constants/mock-editor"
import { useEditorStore } from "@/lib/store/editor-store"
import {
  DEFAULT_TEXT_STYLE,
  EDITOR_FONT_FAMILIES,
  FONT_WEIGHT_OPTIONS,
  type EditorFontFamily,
  type FeatureChipDraft,
  type TextLayerStyle,
} from "@/types/canvas"
import { cn } from "@/lib/utils"

const FONT_CSS: Record<EditorFontFamily, string> = {
  Inter: "var(--font-inter), Inter, sans-serif",
  Montserrat: "var(--font-montserrat), Montserrat, sans-serif",
  Roboto: "var(--font-roboto), Roboto, sans-serif",
  "Space Grotesk": "var(--font-space-grotesk), 'Space Grotesk', sans-serif",
}

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

const DEFAULT_CHIP: FeatureChipDraft = {
  label: "Эко-формула",
  subtitle: "Натуральные ингредиенты",
  bgColor: "rgba(15,17,21,0.45)",
  borderRadius: 14,
  iconId: "icon_leaf",
  variant: "glass",
  textColor: "#FFFFFF",
  blur: 12,
}

function FieldLabel({
  children,
  htmlFor,
}: {
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
    >
      {children}
    </label>
  )
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function ColorPicker({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string
  label: string
  value: string
  disabled?: boolean
  onChange: (hex: string) => void
}) {
  const hex = value.length >= 7 ? value.slice(0, 7) : value

  return (
    <div className="space-y-1.5">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div
        className={cn(
          "flex h-8 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-2",
          disabled && "opacity-50"
        )}
      >
        <label
          htmlFor={id}
          className={cn(
            "relative size-5 shrink-0 overflow-hidden rounded-md ring-1 ring-white/20",
            disabled ? "pointer-events-none" : "cursor-pointer"
          )}
        >
          <span
            className="absolute inset-0"
            style={{ backgroundColor: hex }}
            aria-hidden
          />
          <input
            id={id}
            type="color"
            value={hex}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
          />
        </label>
        <Input
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="h-6 border-0 bg-transparent px-0 font-mono text-[11px] shadow-none focus-visible:ring-0"
          aria-label={label}
        />
      </div>
    </div>
  )
}

function textShadowCss(style: TextLayerStyle): string | undefined {
  if (!style.shadowEnabled) return undefined
  return `${style.shadowOffsetX}px ${style.shadowOffsetY}px ${style.shadowBlur}px ${style.shadowColor}`
}

function TextLayerControl({ className }: { className?: string }) {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const addLayer = useEditorStore((s) => s.addLayer)
  const flashLayer = useEditorStore((s) => s.flashLayer)

  const layer = layers.find((l) => l.id === selectedLayerId)
  const isText = layer?.type === "text"
  const disabled = !isText || Boolean(layer?.locked)
  const style: TextLayerStyle = {
    ...DEFAULT_TEXT_STYLE,
    ...layer?.textStyle,
  }

  const [chipDraft, setChipDraft] = useState<FeatureChipDraft>(DEFAULT_CHIP)

  const patchStyle = (patch: Partial<TextLayerStyle>) => {
    if (!layer || layer.type !== "text") return
    updateLayer(layer.id, {
      textStyle: { ...style, ...patch },
    })
  }

  const addFeatureChip = () => {
    const label = chipDraft.label.trim() || "Преимущество"
    const existing = layers.find(
      (l) =>
        l.chip &&
        l.chip.label.trim().toLocaleLowerCase("ru-RU") ===
          label.toLocaleLowerCase("ru-RU")
    )
    if (existing) {
      flashLayer(existing.id)
      toast.message(`Плашка «${label}» уже на холсте`)
      return
    }

    const chipCount = layers.filter((l) => l.chip).length
    const pos = nextBadgePosition(chipCount)
    const maxZ = layers.reduce((m, l) => Math.max(m, l.zIndex), 0)
    const id = `chip_${Date.now()}`
    addLayer({
      id,
      type: "shape",
      name: `Плашка «${label}»`,
      visible: true,
      locked: false,
      opacity: 1,
      zIndex: maxZ + 1,
      x: pos.x,
      y: pos.y,
      scale: 1,
      rotation: 0,
    chip: {
      ...chipDraft,
      label,
      blur: chipDraft.blur ?? (chipDraft.variant === "glass" ? 12 : 0),
      textColor:
        chipDraft.textColor ??
        (chipDraft.variant === "glass" ? "#FFFFFF" : undefined),
    },
  })
    toast.success(`Плашка «${label}» на холсте`)
  }

  const ChipIcon = CHIP_ICON_MAP[chipDraft.iconId] ?? CircleCheck
  const isGlassChip = chipDraft.variant === "glass"
  const chipTextColor =
    isGlassChip ||
    chipDraft.bgColor.toLowerCase() === "#ffffff" ||
    chipDraft.bgColor.toLowerCase() === "#fff"
      ? isGlassChip
        ? "#FFFFFF"
        : "#0F1115"
      : "#FFFFFF"

  return (
    <div className={cn("space-y-5", className)}>
      {!isText && (
        <div className="rounded-lg border border-dashed border-white/12 bg-white/[0.02] px-3 py-4 text-center text-xs text-muted-foreground">
          Выберите текстовый слой, чтобы править типографику
        </div>
      )}

      <section className={cn("space-y-3", !isText && "opacity-50")}>
        <div className="flex items-center gap-2">
          <Type className="size-4 text-copper" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            Шрифт
          </h3>
        </div>

        <div className="space-y-1.5">
          <FieldLabel>Семейство</FieldLabel>
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

        {isText && (
          <p
            className="truncate rounded-lg border border-white/8 bg-loft/50 px-3 py-2.5 text-sm text-white"
            style={{
              fontFamily: FONT_CSS[style.fontFamily],
              fontWeight: style.fontWeight,
              fontSize: Math.min(style.fontSize, 22),
              color: style.color,
              WebkitTextStroke:
                style.strokeWidth > 0
                  ? `${Math.min(style.strokeWidth, 2)}px ${style.strokeColor}`
                  : undefined,
              textShadow: textShadowCss(style),
            }}
          >
            {layer?.text || layer?.name || "Aa"}
          </p>
        )}
      </section>

      <section
        className={cn(
          "space-y-4 border-t border-white/8 pt-4",
          !isText && "opacity-50"
        )}
      >
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          Стиль текста
        </h3>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <FieldLabel>Размер</FieldLabel>
            <span className="font-mono text-[11px] text-foreground/80">
              {style.fontSize}px
            </span>
          </div>
          <Slider
            min={12}
            max={128}
            step={1}
            disabled={disabled}
            value={[style.fontSize]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              if (typeof next === "number") {
                patchStyle({ fontSize: clamp(next, 12, 128) })
              }
            }}
          />
        </div>

        <div className="space-y-1.5">
          <FieldLabel>Жирность</FieldLabel>
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={disabled}
              className={cn(
                "inline-flex h-8 w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-xs outline-none",
                "focus-visible:ring-2 focus-visible:ring-ring/50",
                "disabled:pointer-events-none disabled:opacity-50"
              )}
            >
              <span>
                {FONT_WEIGHT_OPTIONS.find((w) => w.value === style.fontWeight)
                  ?.label ?? style.fontWeight}
              </span>
              <ChevronDown className="size-3.5 opacity-60" aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[var(--anchor-width)]">
              <DropdownMenuRadioGroup
                value={String(style.fontWeight)}
                onValueChange={(v) => {
                  const n = Number.parseInt(v, 10)
                  if (!Number.isNaN(n)) patchStyle({ fontWeight: n })
                }}
              >
                {FONT_WEIGHT_OPTIONS.map((w) => (
                  <DropdownMenuRadioItem
                    key={w.value}
                    value={String(w.value)}
                    className="text-xs"
                    style={{ fontWeight: w.value }}
                  >
                    {w.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <ColorPicker
          id="text-fill-color"
          label="Цвет"
          value={style.color}
          disabled={disabled}
          onChange={(color) => patchStyle({ color })}
        />

        <div className="space-y-3 rounded-lg border border-white/8 bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Внешняя обводка
          </p>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <FieldLabel>Stroke width</FieldLabel>
              <span className="font-mono text-[11px] text-foreground/80">
                {style.strokeWidth}px
              </span>
            </div>
            <Slider
              min={0}
              max={12}
              step={0.5}
              disabled={disabled}
              value={[style.strokeWidth]}
              onValueChange={(v) => {
                const next = Array.isArray(v) ? v[0] : v
                if (typeof next === "number") {
                  patchStyle({ strokeWidth: clamp(next, 0, 12) })
                }
              }}
            />
          </div>
          <ColorPicker
            id="text-stroke-color"
            label="Stroke color"
            value={style.strokeColor}
            disabled={disabled || style.strokeWidth <= 0}
            onChange={(strokeColor) => patchStyle({ strokeColor })}
          />
        </div>

        <div className="space-y-3 rounded-lg border border-white/8 bg-white/[0.02] p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Тень текста
            </p>
            <button
              type="button"
              role="switch"
              aria-checked={style.shadowEnabled}
              disabled={disabled}
              onClick={() =>
                patchStyle({ shadowEnabled: !style.shadowEnabled })
              }
              className={cn(
                "relative h-5 w-9 rounded-full transition-colors disabled:opacity-50",
                style.shadowEnabled ? "bg-emerald" : "bg-white/15"
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
                  style.shadowEnabled && "translate-x-4"
                )}
              />
              <span className="sr-only">Тень текста</span>
            </button>
          </div>

          <div
            className={cn(
              "space-y-3 transition-opacity",
              !style.shadowEnabled && "opacity-40"
            )}
          >
            <ColorPicker
              id="text-shadow-color"
              label="Цвет тени"
              value={style.shadowColor.slice(0, 7)}
              disabled={disabled || !style.shadowEnabled}
              onChange={(shadowColor) => patchStyle({ shadowColor })}
            />
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <FieldLabel>Размытие</FieldLabel>
                <span className="font-mono text-[11px] text-foreground/80">
                  {style.shadowBlur}px
                </span>
              </div>
              <Slider
                min={0}
                max={32}
                step={1}
                disabled={disabled || !style.shadowEnabled}
                value={[style.shadowBlur]}
                onValueChange={(v) => {
                  const next = Array.isArray(v) ? v[0] : v
                  if (typeof next === "number") {
                    patchStyle({ shadowBlur: clamp(next, 0, 32) })
                  }
                }}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <FieldLabel htmlFor="shadow-ox">Offset X</FieldLabel>
                <Input
                  id="shadow-ox"
                  type="number"
                  disabled={disabled || !style.shadowEnabled}
                  value={style.shadowOffsetX}
                  onChange={(e) =>
                    patchStyle({
                      shadowOffsetX: Number.parseInt(e.target.value, 10) || 0,
                    })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="shadow-oy">Offset Y</FieldLabel>
                <Input
                  id="shadow-oy"
                  type="number"
                  disabled={disabled || !style.shadowEnabled}
                  value={style.shadowOffsetY}
                  onChange={(e) =>
                    patchStyle({
                      shadowOffsetY: Number.parseInt(e.target.value, 10) || 0,
                    })
                  }
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-3 border-t border-white/8 pt-4">
        <div>
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            Feature Chips
          </h3>
          <p className="text-[11px] text-muted-foreground">
            Готовые плашки инфографики с иконкой преимущества
          </p>
        </div>

        <div
          className={cn(
            "inline-flex max-w-full items-center gap-2 border px-3 py-2 text-xs font-medium",
            isGlassChip &&
              "border-white/25 bg-white/10 text-white shadow-sm backdrop-blur-md"
          )}
          style={{
            backgroundColor: isGlassChip ? undefined : chipDraft.bgColor,
            color: chipTextColor,
            borderRadius: chipDraft.borderRadius,
            borderColor: isGlassChip ? undefined : "rgba(15,23,42,0.12)",
          }}
        >
          {isGlassChip ? (
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-white/30 bg-white/10">
              <ChipIcon className="size-3.5" aria-hidden />
            </span>
          ) : (
            <ChipIcon className="size-4 shrink-0" aria-hidden />
          )}
          <span className="min-w-0">
            <span className="block whitespace-nowrap">
              {chipDraft.label || "Преимущество"}
            </span>
            {chipDraft.subtitle ? (
              <span className="block whitespace-nowrap text-[10px] font-normal opacity-70">
                {chipDraft.subtitle}
              </span>
            ) : null}
          </span>
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="chip-label">Текст плашки</FieldLabel>
          <Input
            id="chip-label"
            value={chipDraft.label}
            maxLength={48}
            placeholder="Оригинал"
            onChange={(e) =>
              setChipDraft((d) => ({ ...d, label: e.target.value }))
            }
          />
        </div>

        <div className="space-y-1.5">
          <FieldLabel>Цвет подложки</FieldLabel>
          <div className="flex flex-wrap items-center gap-2">
            {FEATURE_CHIP_BG_PRESETS.map((hex) => (
              <button
                key={hex}
                type="button"
                title={hex}
                onClick={() =>
                  setChipDraft((d) => ({
                    ...d,
                    bgColor: hex,
                    variant: "solid",
                  }))
                }
                className={cn(
                  "size-7 rounded-md ring-1 ring-white/15 transition-transform hover:scale-105",
                  chipDraft.bgColor.toLowerCase() === hex.toLowerCase() &&
                    "ring-2 ring-emerald"
                )}
                style={{ backgroundColor: hex }}
              >
                {chipDraft.bgColor.toLowerCase() === hex.toLowerCase() && (
                  <Check
                    className={cn(
                      "mx-auto size-3.5",
                      hex === "#FFFFFF" || hex === "#F59E0B"
                        ? "text-loft"
                        : "text-white"
                    )}
                    aria-hidden
                  />
                )}
                <span className="sr-only">{hex}</span>
              </button>
            ))}
            <label className="relative size-7 cursor-pointer overflow-hidden rounded-md ring-1 ring-white/15">
              <span
                className="absolute inset-0"
                style={{ backgroundColor: chipDraft.bgColor }}
                aria-hidden
              />
              <input
                type="color"
                value={
                  chipDraft.bgColor.length >= 7
                    ? chipDraft.bgColor.slice(0, 7)
                    : chipDraft.bgColor
                }
                onChange={(e) =>
                  setChipDraft((d) => ({ ...d, bgColor: e.target.value }))
                }
                className="absolute inset-0 size-full cursor-pointer opacity-0"
                aria-label="Свой цвет подложки"
              />
            </label>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <FieldLabel>Скругление</FieldLabel>
            <span className="font-mono text-[11px] text-foreground/80">
              {chipDraft.borderRadius}px
            </span>
          </div>
          <Slider
            min={0}
            max={40}
            step={1}
            value={[chipDraft.borderRadius]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              if (typeof next === "number") {
                setChipDraft((d) => ({
                  ...d,
                  borderRadius: clamp(next, 0, 40),
                }))
              }
            }}
          />
        </div>

        <div className="space-y-1.5">
          <FieldLabel>Иконка преимущества</FieldLabel>
          <div className="grid grid-cols-4 gap-1.5">
            {FEATURE_CHIP_ICONS.map((icon) => {
              const Icon = CHIP_ICON_MAP[icon.id] ?? Sparkles
              const selected = chipDraft.iconId === icon.id
              return (
                <button
                  key={icon.id}
                  type="button"
                  title={icon.label}
                  onClick={() =>
                    setChipDraft((d) => ({ ...d, iconId: icon.id }))
                  }
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border px-1.5 py-2 text-[9px] transition-colors",
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

        <Button
          type="button"
          className="w-full gap-1.5"
          onClick={addFeatureChip}
        >
          <Plus className="size-4" aria-hidden />
          Добавить плашку
        </Button>
      </section>
    </div>
  )
}

export { TextLayerControl, ColorPicker }
