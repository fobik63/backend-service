"use client"

import { ChevronDown, Images, Lamp, Type } from "lucide-react"

import { SliderControl } from "@/components/editor/slider-control"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useI18n } from "@/lib/i18n"
import {
  PACK_SIZE_OPTIONS,
  useEditorStore,
} from "@/lib/store/editor-store"
import type { PackSize } from "@/lib/export/card-pack"
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

function packSizeToIndex(size: PackSize): number {
  const idx = PACK_SIZE_OPTIONS.indexOf(size)
  return idx >= 0 ? idx : PACK_SIZE_OPTIONS.length - 1
}

function indexToPackSize(index: number): PackSize {
  return PACK_SIZE_OPTIONS[clamp(Math.round(index), 0, PACK_SIZE_OPTIONS.length - 1)]!
}

function TextParamsSection() {
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
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Type className="size-4 text-copper" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          Текст
        </h3>
      </div>

      {!isText ? (
        <p className="text-[11px] text-muted-foreground">
          Выберите текст на холсте
        </p>
      ) : null}

      <div className={cn("space-y-3", !isText && "opacity-45")}>
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Шрифт
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
          label="Размер"
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
  const softbox = useEditorStore((s) => s.softbox)
  const setSoftbox = useEditorStore((s) => s.setSoftbox)
  const disabled = !softbox.enabled

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Lamp className="size-4 text-amber" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            Софтбокс
          </h3>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={softbox.enabled}
          onClick={() => setSoftbox({ enabled: !softbox.enabled })}
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors",
            softbox.enabled ? "bg-emerald" : "bg-white/15"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
              softbox.enabled && "translate-x-4"
            )}
          />
          <span className="sr-only">Софтбокс</span>
        </button>
      </div>

      <div className={cn("space-y-3", disabled && "opacity-45")}>
        <SliderControl
          label="Интенсивность"
          value={softbox.intensity}
          min={0}
          max={200}
          unit="%"
          disabled={disabled}
          onChange={(intensity) =>
            setSoftbox({ intensity: clamp(intensity, 0, 200) })
          }
        />
        <SliderControl
          label="Температура"
          value={softbox.colorTempK}
          min={2700}
          max={6500}
          step={50}
          unit="K"
          disabled={disabled}
          formatValue={(v) =>
            `${v}K ${v <= 4000 ? "Warm" : v >= 5600 ? "Cold" : "Neutral"}`
          }
          onChange={(colorTempK) =>
            setSoftbox({ colorTempK: clamp(colorTempK, 2700, 6500) })
          }
          hint={
            <div className="flex justify-between">
              <span>2700 Warm</span>
              <span>6500 Cold</span>
            </div>
          }
        />
        <SliderControl
          label="Угол"
          value={softbox.lightAngle}
          min={0}
          max={360}
          unit="°"
          disabled={disabled}
          onChange={(lightAngle) =>
            setSoftbox({ lightAngle: ((lightAngle % 360) + 360) % 360 })
          }
          hint={
            <div className="flex justify-between">
              <span>0° справа</span>
              <span>180° слева</span>
            </div>
          }
        />
      </div>
    </section>
  )
}

function PackParamsSection() {
  const { t } = useI18n()
  const packSize = useEditorStore((s) => s.packSize)
  const setPackSize = useEditorStore((s) => s.setPackSize)

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Images className="size-4 text-emerald" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          Генерация сета
        </h3>
      </div>

      <SliderControl
        label={t("export.packSize")}
        value={packSizeToIndex(packSize)}
        min={0}
        max={PACK_SIZE_OPTIONS.length - 1}
        step={1}
        formatValue={() => t("export.packPhotos", { count: String(packSize) })}
        onChange={(index) => setPackSize(indexToPackSize(index))}
        hint={
          <div className="flex justify-between font-mono">
            {PACK_SIZE_OPTIONS.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setPackSize(size)}
                className={cn(
                  "rounded px-1 transition-colors",
                  packSize === size
                    ? "text-emerald"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {size}
              </button>
            ))}
          </div>
        }
      />
    </section>
  )
}

function EditorSettingsPanel() {
  const { t } = useI18n()

  return (
    <aside
      className="flex h-full max-h-[calc(100vh-80px)] w-[280px] shrink-0 flex-col overflow-hidden border-l border-white/8 bg-[#14171d]"
      aria-label={t("editor.tools")}
    >
      <div className="sticky top-0 z-10 shrink-0 border-b border-white/8 bg-[#14171d] px-4 py-3">
        <h2 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.tools")}
        </h2>
        <p className="text-[11px] text-muted-foreground">
          {t("editor.toolsHint")}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-4 py-4">
        <TextParamsSection />
        <div className="border-t border-white/8 pt-4">
          <SoftboxParamsSection />
        </div>
        <div className="border-t border-white/8 pt-4">
          <PackParamsSection />
        </div>
      </div>
    </aside>
  )
}

export { EditorSettingsPanel }
