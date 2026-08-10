"use client"

import { ChevronDown } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  ARTBOARD_FORMAT_PRESETS,
  type ArtboardFormatId,
} from "@/lib/editor/format-presets"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

const MARKETPLACE_ORDER = ["wildberries", "ozon", "yandex"] as const

const MARKETPLACE_LABEL_KEY = {
  wildberries: "formatGroupWb",
  ozon: "formatGroupOzon",
  yandex: "formatGroupYandex",
} as const

type FormatSelectorProps = {
  className?: string
  disabled?: boolean
}

function FormatSelector({ className, disabled = false }: FormatSelectorProps) {
  const { t } = useI18n()
  const artboardFormatId = useEditorStore((s) => s.artboardFormatId)
  const canvasWidth = useEditorStore((s) => s.canvasWidth)
  const canvasHeight = useEditorStore((s) => s.canvasHeight)
  const setArtboardFormat = useEditorStore((s) => s.setArtboardFormat)

  const active =
    ARTBOARD_FORMAT_PRESETS.find((p) => p.id === artboardFormatId) ??
    ARTBOARD_FORMAT_PRESETS[0]!

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={disabled}
        aria-label={t("editor.formatSelector")}
        className={cn(
          "inline-flex h-8 max-w-full items-center gap-1.5 rounded-lg border border-white/12 bg-loft-surface px-2.5 text-xs",
          "text-foreground outline-none transition-colors",
          "hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-ring/50",
          "disabled:pointer-events-none disabled:opacity-50",
          className
        )}
      >
        <span className="truncate font-medium">
          {t(`editor.${active.labelKey}`)}
        </span>
        <span className="hidden font-mono text-[10px] text-muted-foreground sm:inline">
          {canvasWidth}×{canvasHeight}
        </span>
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuLabel>{t("editor.formatSelector")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={artboardFormatId}
          onValueChange={(value) =>
            setArtboardFormat(value as ArtboardFormatId)
          }
        >
          {MARKETPLACE_ORDER.map((marketplace, groupIndex) => {
            const presets = ARTBOARD_FORMAT_PRESETS.filter(
              (p) => p.marketplace === marketplace
            )
            if (presets.length === 0) return null
            return (
              <DropdownMenuGroup key={marketplace}>
                {groupIndex > 0 ? <DropdownMenuSeparator /> : null}
                <DropdownMenuLabel className="text-[10px] text-muted-foreground">
                  {t(`editor.${MARKETPLACE_LABEL_KEY[marketplace]}`)}
                </DropdownMenuLabel>
                {presets.map((preset) => (
                  <DropdownMenuRadioItem key={preset.id} value={preset.id}>
                    <span className="flex w-full items-center justify-between gap-3">
                      <span>{t(`editor.${preset.labelKey}`)}</span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {preset.width}×{preset.height}
                      </span>
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuGroup>
            )
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { FormatSelector }
export type { FormatSelectorProps }
