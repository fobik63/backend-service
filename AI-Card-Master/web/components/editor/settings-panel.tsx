"use client"

import {
  ChevronDown,
  EyeOff,
  Lamp,
  Layers,
  Lock,
  RotateCw,
  SlidersHorizontal,
  Sparkles,
  Type,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { BadgeParamsSection } from "@/components/editor/badge-tool"
import { LayerTreePanel } from "@/components/editor/layer-tree"
import { SliderControl } from "@/components/editor/slider-control"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Input } from "@/components/ui/input"
import { TEXT_PRESETS } from "@/lib/constants/mock-editor"
import { addTextPresetToCanvas } from "@/lib/editor/canvas-actions"
import { ensureEditorFontLoaded } from "@/lib/editor/fabric-fonts"
import { useI18n } from "@/lib/i18n"
import {
  useEditorStore,
  type ProductColorGrade,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import {
  DEFAULT_TEXT_STYLE,
  EDITOR_FONT_FAMILIES,
  type EditorFontFamily,
  type TextLayerStyle,
} from "@/types/canvas"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

const FONT_CSS: Record<EditorFontFamily, string> = {
  Inter: "var(--font-inter), Inter, sans-serif",
  Montserrat: "var(--font-montserrat), Montserrat, sans-serif",
  Unbounded: "var(--font-unbounded), Unbounded, sans-serif",
  "Cera Pro": "var(--font-cera-pro), 'Cera Pro', sans-serif",
  Oswald: "var(--font-oswald), Oswald, sans-serif",
  "Russo One": "var(--font-russo-one), 'Russo One', sans-serif",
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
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Type className="size-4 text-copper" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            {t("editor.text")}
          </h3>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 text-[11px]",
              "text-muted-foreground outline-none transition-colors hover:text-foreground",
              "focus-visible:ring-2 focus-visible:ring-ring/50",
            )}
          >
            <Type className="size-3" aria-hidden />
            {t("editor.addText")}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-48">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("editor.addText")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {TEXT_PRESETS.map((preset) => (
                <DropdownMenuItem
                  key={preset.id}
                  onClick={() => {
                    const label = addTextPresetToCanvas(preset)
                    toast.success(`Текст «${label}» добавлен`)
                  }}
                >
                  <div className="flex flex-col gap-0.5">
                    <span>{preset.label}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {preset.sample}
                    </span>
                  </div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {!isText ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.textSelectHint")}
        </p>
      ) : null}

      <div className={cn("space-y-2.5", !isText && "opacity-45")}>
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.text")}
          </span>
          <Input
            value={layer?.type === "text" ? (layer.text ?? "") : ""}
            disabled={disabled}
            onChange={(e) => {
              if (!layer || layer.type !== "text") return
              updateLayer(layer.id, { text: e.target.value })
            }}
            className="h-8 border-white/10 bg-white/[0.04] text-xs"
          />
        </div>

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
                "disabled:pointer-events-none disabled:opacity-50",
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
                  if (!EDITOR_FONT_FAMILIES.includes(v as EditorFontFamily)) {
                    return
                  }
                  const font = v as EditorFontFamily
                  void (async () => {
                    await ensureEditorFontLoaded(font, {
                      sizePx: style.fontSize,
                      weight: style.fontWeight,
                    })
                    patchStyle({ fontFamily: font })
                  })()
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
  const beginHistoryTransaction = useEditorStore((s) => s.beginHistoryTransaction)
  const commitHistoryTransaction = useEditorStore(
    (s) => s.commitHistoryTransaction
  )

  const [draft, setDraft] = useState<SoftboxSettings>(softbox)
  const draftRef = useRef(draft)
  const scrubbingRef = useRef(false)

  useEffect(() => {
    if (scrubbingRef.current) return
    setDraft(softbox)
    draftRef.current = softbox
  }, [softbox])

  useEffect(() => {
    return () => {
      if (scrubbingRef.current) {
        scrubbingRef.current = false
        const store = useEditorStore.getState()
        store.setSoftbox({ ...draftRef.current })
        store.commitHistoryTransaction()
      }
    }
  }, [])

  const beginScrub = () => {
    if (scrubbingRef.current) return
    scrubbingRef.current = true
    beginHistoryTransaction()
  }

  const endScrub = () => {
    if (!scrubbingRef.current) return
    setSoftbox({ ...draftRef.current })
    scrubbingRef.current = false
    commitHistoryTransaction()
  }

  const patchDraft = (patch: Partial<SoftboxSettings>) => {
    beginScrub()
    const next = { ...draftRef.current, ...patch }
    draftRef.current = next
    setDraft(next)
    setSoftbox({ ...next })
  }

  const disabled = !draft.enabled
  const intensityPct = clamp(draft.intensity, 0, 100)
  const spreadPct = clamp(draft.softboxDiffusion, 10, 100)

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Lamp className="size-4 text-copper" aria-hidden />
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
            setSoftbox({ enabled })
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
          label={t("editor.angle")}
          value={draft.lightAngle}
          min={0}
          max={360}
          unit="°"
          disabled={disabled}
          onChange={(lightAngle) =>
            patchDraft({
              lightAngle: ((Math.round(lightAngle) % 360) + 360) % 360,
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
          label={t("editor.intensity")}
          value={intensityPct}
          min={0}
          max={100}
          unit="%"
          disabled={disabled}
          onChange={(intensity) =>
            patchDraft({ intensity: clamp(intensity, 0, 100) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.diffusion")}
          value={spreadPct}
          min={10}
          max={100}
          unit="%"
          disabled={disabled}
          onChange={(softboxDiffusion) =>
            patchDraft({
              softboxDiffusion: clamp(softboxDiffusion, 10, 100),
            })
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
          formatValue={(v) =>
            `${v}K ${
              v <= 4000
                ? t("editor.colorTempWarm")
                : v >= 5600
                  ? t("editor.colorTempCold")
                  : t("editor.colorTempNeutral")
            }`
          }
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
      </div>
    </section>
  )
}

function ColorGradeParamsSection() {
  const { t } = useI18n()
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const colorGrade = useEditorStore((s) => s.colorGrade)
  const backgroundColorGrade = useEditorStore((s) => s.backgroundColorGrade)
  const setColorGrade = useEditorStore((s) => s.setColorGrade)
  const setBackgroundColorGrade = useEditorStore(
    (s) => s.setBackgroundColorGrade
  )
  const beginHistoryTransaction = useEditorStore(
    (s) => s.beginHistoryTransaction,
  )
  const commitHistoryTransaction = useEditorStore(
    (s) => s.commitHistoryTransaction,
  )

  const selectedLayer = layers.find((l) => l.id === selectedLayerId)
  const target =
    selectedLayer?.type === "background" ? "background" : "product"
  const canEdit =
    !selectedLayer ||
    selectedLayer.type === "background" ||
    selectedLayer.type === "image"
  const activeColorGrade =
    target === "background" ? backgroundColorGrade : colorGrade
  const setActiveColorGrade =
    target === "background" ? setBackgroundColorGrade : setColorGrade

  const [draft, setDraft] = useState<ProductColorGrade>(activeColorGrade)
  const draftRef = useRef(draft)
  const scrubbingRef = useRef(false)

  useEffect(() => {
    if (scrubbingRef.current) return
    setDraft(activeColorGrade)
    draftRef.current = activeColorGrade
  }, [activeColorGrade])

  useEffect(() => {
    return () => {
      if (scrubbingRef.current) {
        scrubbingRef.current = false
        const store = useEditorStore.getState()
        if (target === "background") {
          store.setBackgroundColorGrade({ ...draftRef.current })
        } else {
          store.setColorGrade({ ...draftRef.current })
        }
        store.commitHistoryTransaction()
      }
    }
  }, [target])

  const pushDraftToStore = (next: ProductColorGrade) => {
    setActiveColorGrade({ ...next })
  }

  const beginScrub = () => {
    if (scrubbingRef.current) return
    scrubbingRef.current = true
    beginHistoryTransaction()
  }

  const endScrub = () => {
    if (!scrubbingRef.current) return
    pushDraftToStore(draftRef.current)
    scrubbingRef.current = false
    commitHistoryTransaction()
  }

  const patchDraft = (patch: Partial<ProductColorGrade>) => {
    beginScrub()
    const next = { ...draftRef.current, ...patch }
    draftRef.current = next
    setDraft(next)
    pushDraftToStore(next)
  }

  const rimDisabled = !draft.rimEnabled

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-copper" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {target === "background"
            ? t("editor.colorGradeBackground")
            : t("editor.colorGradeProduct")}
        </h3>
      </div>

      {!canEdit ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.colorGradeSelectHint")}
        </p>
      ) : null}

      <div className={cn("space-y-2.5", !canEdit && "opacity-45")}>
        <SliderControl
          label={t("editor.brightness")}
          value={draft.brightness}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(brightness) =>
            patchDraft({ brightness: clamp(brightness, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.contrast")}
          value={draft.contrast}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(contrast) =>
            patchDraft({ contrast: clamp(contrast, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.saturation")}
          value={draft.saturation}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(saturation) =>
            patchDraft({ saturation: clamp(saturation, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.hue")}
          value={draft.hue}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(hue) =>
            patchDraft({ hue: clamp(hue, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.productTint")}
          value={draft.temperature}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(temperature) =>
            patchDraft({ temperature: clamp(temperature, -1, 1) })
          }
          onValueCommitted={endScrub}
          hint={
            <div className="flex justify-between">
              <span>{t("editor.colorTempCold")}</span>
              <span>{t("editor.colorTempWarm")}</span>
            </div>
          }
        />
        <SliderControl
          label={t("editor.highlights")}
          value={draft.highlights}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(highlights) =>
            patchDraft({ highlights: clamp(highlights, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.shadowsTone")}
          value={draft.shadows}
          min={-1}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(shadows) =>
            patchDraft({ shadows: clamp(shadows, -1, 1) })
          }
          onValueCommitted={endScrub}
        />
        <SliderControl
          label={t("editor.sharpness")}
          value={draft.sharpness}
          min={0}
          max={1}
          step={0.01}
          disabled={!canEdit}
          formatValue={(v) => v.toFixed(2)}
          onChange={(sharpness) =>
            patchDraft({ sharpness: clamp(sharpness, 0, 1) })
          }
          onValueCommitted={endScrub}
        />

        {target === "product" ? (
          <>
            <div className="flex items-center justify-between gap-2 pt-1">
              <span className="text-[11px] text-muted-foreground">
                {t("editor.rimLight")}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={draft.rimEnabled}
                disabled={!canEdit}
                onClick={() => {
                  const rimEnabled = !draft.rimEnabled
                  const next = { ...draftRef.current, rimEnabled }
                  draftRef.current = next
                  setDraft(next)
                  beginHistoryTransaction()
                  pushDraftToStore(next)
                  commitHistoryTransaction()
                }}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors disabled:pointer-events-none disabled:opacity-50",
                  draft.rimEnabled ? "bg-foreground" : "bg-white/15",
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
                    draft.rimEnabled && "translate-x-4",
                  )}
                />
                <span className="sr-only">{t("editor.rimLight")}</span>
              </button>
            </div>

            <div className={cn("space-y-2.5", rimDisabled && "opacity-45")}>
              <SliderControl
                label={t("editor.rimStrength")}
                value={draft.rimStrength}
                min={0}
                max={100}
                unit="%"
                disabled={!canEdit || rimDisabled}
                onChange={(rimStrength) =>
                  patchDraft({ rimStrength: clamp(rimStrength, 0, 100) })
                }
                onValueCommitted={endScrub}
              />
              <label className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                <span>{t("editor.rimColor")}</span>
                <input
                  type="color"
                  value={draft.rimColor}
                  disabled={!canEdit || rimDisabled}
                  onChange={(e) => {
                    beginHistoryTransaction()
                    const next = {
                      ...draftRef.current,
                      rimColor: e.target.value,
                    }
                    draftRef.current = next
                    setDraft(next)
                    pushDraftToStore(next)
                    commitHistoryTransaction()
                  }}
                  className="size-7 cursor-pointer rounded border border-white/15 bg-transparent disabled:cursor-not-allowed"
                />
              </label>
            </div>
          </>
        ) : null}
      </div>
    </section>
  )
}

function LayerParamsSection() {
  const { t } = useI18n()
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const updateLayer = useEditorStore((s) => s.updateLayer)

  const layer = layers.find((l) => l.id === selectedLayerId)
  const hasSelection = Boolean(layer)
  const disabled = !hasSelection || Boolean(layer?.locked)
  const opacityPct = Math.round((layer?.opacity ?? 1) * 100)
  const rotation = Math.round(layer?.rotation ?? 0)

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Layers className="size-4 text-copper" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.layerProps")}
        </h3>
      </div>

      {!hasSelection ? (
        <p className="text-[11px] text-muted-foreground">
          {t("editor.layerSelectHint")}
        </p>
      ) : (
        <p className="truncate text-[11px] text-muted-foreground">
          {layer?.name}
        </p>
      )}

      <div className={cn("space-y-2.5", !hasSelection && "opacity-45")}>
        <SliderControl
          label={t("editor.opacity")}
          value={opacityPct}
          min={0}
          max={100}
          unit="%"
          disabled={!hasSelection || Boolean(layer?.locked)}
          onChange={(pct) => {
            if (!layer) return
            updateLayer(layer.id, { opacity: clamp(pct, 0, 100) / 100 })
          }}
        />

        <SliderControl
          label={t("editor.rotation")}
          value={rotation}
          min={0}
          max={360}
          unit="°"
          disabled={disabled}
          onChange={(deg) => {
            if (!layer) return
            updateLayer(layer.id, {
              rotation: ((Math.round(deg) % 360) + 360) % 360,
            })
          }}
        />

        <div className="flex flex-wrap gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!hasSelection}
            className="h-8 flex-1 gap-1.5 border-white/10 bg-white/[0.04] text-xs"
            onClick={() => {
              if (!layer) return
              updateLayer(layer.id, { visible: !layer.visible })
            }}
          >
            <EyeOff className="size-3.5" aria-hidden />
            {layer?.visible === false
              ? t("editor.layerShow")
              : t("editor.layerHide")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!hasSelection}
            className="h-8 flex-1 gap-1.5 border-white/10 bg-white/[0.04] text-xs"
            onClick={() => {
              if (!layer) return
              updateLayer(layer.id, { locked: !layer.locked })
            }}
          >
            <Lock className="size-3.5" aria-hidden />
            {layer?.locked ? t("editor.layerUnlock") : t("editor.layerLock")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            className="h-8 flex-1 gap-1.5 border-white/10 bg-white/[0.04] text-xs"
            onClick={() => {
              if (!layer) return
              const next = (((layer.rotation ?? 0) + 90) % 360 + 360) % 360
              updateLayer(layer.id, { rotation: next })
            }}
          >
            <RotateCw className="size-3.5" aria-hidden />
            {t("editor.rotate90")}
          </Button>
        </div>
      </div>
    </section>
  )
}

function EditorSettingsBody() {
  const { t } = useI18n()
  const safeZoneMask = useEditorStore((s) => s.safeZoneMask)
  const safeZoneWarnings = useEditorStore((s) => s.safeZoneWarnings)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-white/8 px-3 py-2.5">
        <h2 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.tools")}
        </h2>
        <p className="text-[11px] text-muted-foreground">
          {t("editor.toolsHint")}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-3 py-3 pb-12">
        {safeZoneMask !== "off" && safeZoneWarnings.length > 0 ? (
          <div
            className="space-y-1.5 rounded-lg border border-amber-500/35 bg-amber-500/10 px-2.5 py-2"
            role="alert"
            aria-live="polite"
          >
            {safeZoneWarnings.map((w) => (
              <p
                key={w.zoneId}
                className="text-[11px] leading-snug text-amber-100/95"
              >
                {t(`editor.${w.warningKey}`)}
              </p>
            ))}
          </div>
        ) : null}
        <LayerTreePanel />
        <div className="border-t border-white/8 pt-3">
          <TextParamsSection />
        </div>
        <div className="border-t border-white/8 pt-3">
          <BadgeParamsSection />
        </div>
        <div className="border-t border-white/8 pt-3">
          <LayerParamsSection />
        </div>
        <div className="border-t border-white/8 pt-3">
          <SoftboxParamsSection />
        </div>
        <div className="border-t border-white/8 pt-3">
          <ColorGradeParamsSection />
        </div>
      </div>
    </div>
  )
}

/** Viewport minus editor header (h-12) and workspace padding (p-3 × 2). */
const PANEL_SHELL =
  "flex h-[calc(100dvh-4.5rem)] max-h-[calc(100dvh-4.5rem)] min-h-0 flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/80 backdrop-blur-xl"

function EditorSettingsPanel(_props: EditorSettingsPanelProps) {
  const { t } = useI18n()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      <aside
        className={cn(
          "hidden w-[min(100%,360px)] shrink-0 lg:flex",
          "lg:w-[clamp(20rem,22vw,22.5rem)]",
          PANEL_SHELL,
        )}
        aria-label={t("editor.tools")}
      >
        <EditorSettingsBody />
      </aside>

      <div className="pointer-events-none absolute right-3 bottom-[9.75rem] z-20 sm:bottom-[10.25rem] lg:hidden">
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
            className="flex h-full min-h-0 w-full max-w-[min(100%,24rem)] flex-col border-l border-zinc-800 bg-zinc-900/90 p-0 backdrop-blur-xl"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{t("editor.tools")}</SheetTitle>
              <SheetDescription>{t("editor.toolsHint")}</SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <EditorSettingsBody />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  )
}

export { EditorSettingsPanel }
export type { EditorSettingsPanelProps }
