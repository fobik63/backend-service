"use client"

import { Archive, ChevronDown, Download, Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
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
import { getApiErrorMessage } from "@/lib/api"
import {
  clampPackSize,
  downloadCardPackZip,
  findEditorExportCanvas,
  PRESET_PACK_SIZES,
  type PackSize,
} from "@/lib/export/card-pack"
import { captureFabricPagesPngBytes } from "@/lib/editor/fabric-export"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"
import type { CanvasLayer } from "@/types/canvas"
import type { SoftboxSettings } from "@/lib/store/editor-store"

type ExportButtonProps = {
  className?: string
  /** Override project title used in ZIP filename / slides. */
  projectTitle?: string
  /** Optional product image when canvas capture is unavailable. */
  productImageUrl?: string | null
  pages?: CanvasLayer[][]
  softbox?: SoftboxSettings
  /** Compact mode for project cards / toolbars. */
  variant?: "editor" | "compact"
  disabled?: boolean
}

function ExportButton({
  className,
  projectTitle,
  productImageUrl,
  pages: projectPages,
  softbox: projectSoftbox,
  variant = "editor",
  disabled = false,
}: ExportButtonProps) {
  const { t } = useI18n()
  const [localPackSize, setLocalPackSize] = useState<PackSize>(5)
  const [exporting, setExporting] = useState(false)

  const storeProjectId = useEditorStore((s) => s.projectId)
  const layers = useEditorStore((s) => s.layers)
  const storePreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const storePackSize = useEditorStore((s) => s.packSize)
  const storePages = useEditorStore((s) => s.pages)
  const storeSoftbox = useEditorStore((s) => s.softbox)
  const setStorePackSize = useEditorStore((s) => s.setPackSize)

  /** Editor variant reads/writes shared store; compact keeps local state. */
  const packSize = variant === "editor" ? storePackSize : localPackSize
  const setPackSize =
    variant === "editor" ? setStorePackSize : setLocalPackSize

  const title =
    projectTitle?.trim() ||
    layers.find((l) => l.type === "text" && l.text?.trim())?.text?.trim() ||
    storeProjectId ||
    "card-pack"

  const handleDownload = async () => {
    if (exporting || disabled) return
    setExporting(true)
    try {
      const canvasEl = findEditorExportCanvas()
      const pages = projectPages ?? (variant === "editor" ? storePages : undefined)

      let fabricPages: Uint8Array[] | null = null
      if (variant === "editor" && pages?.length) {
        try {
          useEditorStore.getState().commitActivePage()
          fabricPages = await captureFabricPagesPngBytes({
            pageCount: Math.min(packSize, pages.length),
            getActivePageIndex: () => useEditorStore.getState().activePageIndex,
            setActivePageIndex: (index) =>
              useEditorStore.getState().setActivePageIndex(index),
          })
        } catch {
          fabricPages = null
        }
      }

      await downloadCardPackZip({
        packSize,
        projectTitle: title,
        canvasEl,
        productImageUrl: productImageUrl ?? storePreviewUrl,
        layers: projectPages?.[0] ?? layers,
        pages,
        softbox: projectSoftbox ?? (variant === "editor" ? storeSoftbox : undefined),
        zipBasename: title,
        capturePageAtIndex: fabricPages
          ? async (pageIndex) => {
              const hit = fabricPages![pageIndex]
              if (hit) return hit
              return fabricPages![fabricPages!.length - 1]!
            }
          : undefined,
      })
      toast.success(
        t("export.success", {
          count: String(packSize),
        })
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("export.error")))
    } finally {
      setExporting(false)
    }
  }

  const packLabel = t("export.packPhotos", { count: String(packSize) })

  if (variant === "compact") {
    return (
      <div className={cn("inline-flex flex-wrap items-center gap-2", className)}>
        <div
          className="inline-flex overflow-hidden rounded-lg border border-white/12 bg-white/5"
          role="group"
          aria-label={t("export.packSize")}
        >
          {PRESET_PACK_SIZES.map((size) => (
            <button
              key={size}
              type="button"
              disabled={exporting || disabled}
              onClick={() => setPackSize(size)}
              className={cn(
                "px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                packSize === size
                  ? "bg-emerald/20 text-emerald"
                  : "text-muted-foreground hover:text-foreground"
              )}
              aria-pressed={packSize === size}
            >
              {size}
            </button>
          ))}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={exporting || disabled}
          onClick={() => void handleDownload()}
          className="gap-1.5 border-white/12 bg-white/5"
          aria-busy={exporting}
        >
          {exporting ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Download className="size-3.5" aria-hidden />
          )}
          {t("export.downloadZip")}
        </Button>
      </div>
    )
  }

  return (
    <div
      className={cn(
        "inline-flex h-12 overflow-hidden rounded-lg border border-white/12 bg-loft/50",
        className
      )}
    >
      <Button
        type="button"
        variant="ghost"
        disabled={exporting || disabled}
        onClick={() => void handleDownload()}
        className={cn(
          "h-full gap-2 rounded-none px-3 text-sm text-foreground",
          "hover:bg-white/8 hover:text-foreground"
        )}
        aria-busy={exporting}
      >
        {exporting ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : (
          <Archive className="size-4 text-copper" aria-hidden />
        )}
        <span className="hidden sm:inline">
          {exporting ? t("export.preparing") : t("export.downloadZip")}
        </span>
        <span className="sm:hidden">{t("export.zipShort")}</span>
        <span className="hidden rounded-md bg-white/8 px-1.5 py-0.5 text-[10px] text-muted-foreground md:inline">
          {packLabel}
        </span>
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={exporting || disabled}
          aria-label={t("export.packSize")}
          className={cn(
            "inline-flex h-full w-9 items-center justify-center rounded-none border-l border-white/12",
            "text-muted-foreground outline-none transition-colors",
            "hover:bg-white/8 hover:text-foreground",
            "focus-visible:ring-2 focus-visible:ring-ring/50",
            "disabled:pointer-events-none disabled:opacity-50"
          )}
        >
          <ChevronDown className="size-4" aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" side="top" className="min-w-52">
          <DropdownMenuGroup>
            <DropdownMenuLabel>{t("export.packSize")}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup
              value={String(packSize)}
              onValueChange={(value) =>
                setPackSize(clampPackSize(Number(value)))
              }
            >
              {PRESET_PACK_SIZES.map((size) => (
                <DropdownMenuRadioItem key={size} value={String(size)}>
                  {t("export.packOption", { count: String(size) })}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <button
            type="button"
            disabled={exporting || disabled}
            onClick={() => void handleDownload()}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm",
              "hover:bg-emerald/10 hover:text-emerald",
              "disabled:pointer-events-none disabled:opacity-50"
            )}
          >
            <Download className="size-4" aria-hidden />
            {t("export.downloadZip")}
          </button>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export { ExportButton }
export type { ExportButtonProps, PackSize }
