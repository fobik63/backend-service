"use client"

import {
  Archive,
  ChevronDown,
  Download,
  FileImage,
  ImageIcon,
  Loader2,
  Sparkles,
} from "lucide-react"
import { useState, type FormEvent } from "react"
import { toast } from "sonner"

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
import { GlassButton } from "@/components/ui/glass-button"
import { Textarea } from "@/components/ui/textarea"
import {
  downloadCardPackZip,
  findEditorExportCanvas,
} from "@/lib/export/card-pack"
import { getApiErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type ExportFormat = "png" | "webp"

type PromptBarProps = {
  className?: string
  projectTitle?: string
  /** Vertical block for the right settings panel (default). */
  variant?: "panel" | "footer"
}

function PromptBar({
  className,
  projectTitle,
  variant = "panel",
}: PromptBarProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState("")
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [zipping, setZipping] = useState(false)
  const [exportFormat, setExportFormat] = useState<ExportFormat>("png")

  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const storeProjectId = useEditorStore((s) => s.projectId)
  const layers = useEditorStore((s) => s.layers)
  const storePreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const packSize = useEditorStore((s) => s.packSize)

  const exportOptions = [
    {
      id: "png" as const,
      label: t("editor.exportPng"),
      description: t("editor.exportPngDesc"),
      icon: FileImage,
    },
    {
      id: "webp" as const,
      label: t("editor.exportWebp"),
      description: t("editor.exportWebpDesc"),
      icon: ImageIcon,
    },
  ]

  const zipTitle =
    projectTitle?.trim() ||
    layers.find((l) => l.type === "text" && l.text?.trim())?.text?.trim() ||
    storeProjectId ||
    "card-pack"

  const handleGenerate = async (e?: FormEvent) => {
    e?.preventDefault()
    const trimmed = prompt.trim()
    if (!trimmed) {
      toast.error(t("editor.promptRequired"))
      return
    }
    if (generating) return

    setGenerating(true)
    setBusyKind("generating")
    try {
      await new Promise((r) => setTimeout(r, 1600))
      toast.success(t("editor.generateSuccess"))
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.generateError")))
    } finally {
      setGenerating(false)
      setBusyKind("idle")
    }
  }

  const handleExport = async (format: ExportFormat = exportFormat) => {
    if (exporting) return
    setExportFormat(format)
    setExporting(true)
    try {
      await new Promise((r) => setTimeout(r, 900))
      toast.success(
        `${t("editor.download")}: ${
          format === "png" ? t("editor.exportPng") : t("editor.exportWebp")
        }`
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("export.error")))
    } finally {
      setExporting(false)
    }
  }

  const handleZip = async () => {
    if (zipping) return
    setZipping(true)
    try {
      const canvasEl = findEditorExportCanvas()
      await downloadCardPackZip({
        packSize,
        projectTitle: zipTitle,
        canvasEl,
        productImageUrl: storePreviewUrl,
        layers,
        zipBasename: zipTitle,
      })
      toast.success(
        t("export.success", {
          count: String(packSize),
        })
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("export.error")))
    } finally {
      setZipping(false)
    }
  }

  const activeExport =
    exportOptions.find((o) => o.id === exportFormat) ?? exportOptions[0]
  const busy = generating || exporting || zipping

  if (variant === "footer") {
    return (
      <footer
        className={cn(
          "shrink-0 border-t border-white/8 bg-loft-surface/95 backdrop-blur-sm",
          className
        )}
        aria-label={t("editor.promptBarAria")}
      >
        <form
          onSubmit={handleGenerate}
          className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:gap-3 sm:px-4"
        >
          <div className="relative min-w-0 flex-1">
            <Sparkles
              className="pointer-events-none absolute top-3 left-3 size-4 text-emerald/70"
              aria-hidden
            />
            <Textarea
              id="editor-ai-prompt-footer"
              value={prompt}
              disabled={generating}
              placeholder={t("editor.promptPlaceholder")}
              aria-label={t("editor.promptAria")}
              rows={2}
              onChange={(e) => setPrompt(e.target.value)}
              className={cn(
                "min-h-12 resize-none border-white/10 bg-loft/60 pl-10 text-sm",
                "placeholder:text-muted-foreground/70",
                "focus-visible:border-emerald/40 focus-visible:ring-emerald/25"
              )}
            />
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <GlassButton
              type="submit"
              disabled={generating || !prompt.trim()}
              aria-busy={generating}
            >
              {generating ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-4" aria-hidden />
              )}
              {generating ? t("editor.generating") : t("editor.generate")}
            </GlassButton>
            <Button
              type="button"
              variant="outline"
              disabled={exporting}
              onClick={() => handleExport(exportFormat)}
              className="border-white/12 bg-loft/50"
            >
              <Download className="size-4 text-copper" aria-hidden />
              {t("editor.download")}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={zipping}
              onClick={() => void handleZip()}
              className="border-white/12 bg-loft/50"
            >
              <Archive className="size-4 text-copper" aria-hidden />
              {t("export.downloadZip")}
            </Button>
          </div>
        </form>
      </footer>
    )
  }

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label={t("editor.promptBarAria")}
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-emerald" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.promptSection")}
        </h3>
      </div>

      <form onSubmit={handleGenerate} className="space-y-2.5">
        <Textarea
          id="editor-ai-prompt"
          value={prompt}
          disabled={generating}
          placeholder={t("editor.promptPlaceholder")}
          aria-label={t("editor.promptAria")}
          rows={3}
          onChange={(e) => setPrompt(e.target.value)}
          className={cn(
            "min-h-[4.5rem] resize-none border-white/10 bg-white/[0.04] text-xs leading-relaxed",
            "placeholder:text-muted-foreground/70",
            "focus-visible:border-emerald/40 focus-visible:ring-emerald/25"
          )}
        />

        <div className="grid grid-cols-1 gap-2">
          <GlassButton
            type="submit"
            size="sm"
            disabled={generating || !prompt.trim() || busy}
            className={cn("w-full shadow-emerald-glow", generating && "opacity-90")}
            aria-busy={generating}
          >
            {generating ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-3.5" aria-hidden />
            )}
            {generating ? t("editor.generating") : t("editor.generate")}
          </GlassButton>

          <div className="grid grid-cols-2 gap-2">
            <div className="inline-flex h-9 overflow-hidden rounded-lg border border-white/12 bg-loft/50">
              <Button
                type="button"
                variant="ghost"
                disabled={exporting || busy}
                onClick={() => handleExport(exportFormat)}
                className={cn(
                  "h-full min-w-0 flex-1 gap-1.5 rounded-none px-2 text-xs text-foreground",
                  "hover:bg-white/8 hover:text-foreground"
                )}
                aria-busy={exporting}
              >
                {exporting ? (
                  <Loader2 className="size-3.5 animate-spin shrink-0" aria-hidden />
                ) : (
                  <Download className="size-3.5 shrink-0 text-copper" aria-hidden />
                )}
                <span className="truncate">{t("editor.download")}</span>
              </Button>

              <DropdownMenu>
                <DropdownMenuTrigger
                  disabled={exporting || busy}
                  aria-label={t("editor.exportFormat")}
                  className={cn(
                    "inline-flex h-full w-7 shrink-0 items-center justify-center rounded-none border-l border-white/12",
                    "text-muted-foreground outline-none transition-colors",
                    "hover:bg-white/8 hover:text-foreground",
                    "focus-visible:ring-2 focus-visible:ring-ring/50",
                    "disabled:pointer-events-none disabled:opacity-50"
                  )}
                >
                  <ChevronDown className="size-3.5" aria-hidden />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="top" className="min-w-52">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>
                      {t("editor.exportFormat")}
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {exportOptions.map((opt) => {
                      const Icon = opt.icon
                      const selected = opt.id === exportFormat
                      return (
                        <DropdownMenuItem
                          key={opt.id}
                          onClick={() => handleExport(opt.id)}
                          className={cn(
                            "gap-2.5 py-2",
                            selected && "bg-emerald/10 text-emerald"
                          )}
                        >
                          <Icon
                            className={cn(
                              "size-4",
                              selected ? "text-emerald" : "text-muted-foreground"
                            )}
                            aria-hidden
                          />
                          <span className="flex min-w-0 flex-col gap-0.5">
                            <span className="text-sm font-medium">{opt.label}</span>
                            <span className="text-[11px] text-muted-foreground">
                              {opt.description}
                            </span>
                          </span>
                        </DropdownMenuItem>
                      )
                    })}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={zipping || busy}
              onClick={() => void handleZip()}
              className="h-9 gap-1.5 border-white/12 bg-loft/50 px-2 text-xs"
              aria-busy={zipping}
              title={t("export.packPhotos", { count: String(packSize) })}
            >
              {zipping ? (
                <Loader2 className="size-3.5 animate-spin shrink-0" aria-hidden />
              ) : (
                <Archive className="size-3.5 shrink-0 text-copper" aria-hidden />
              )}
              <span className="truncate">
                {zipping ? t("export.preparing") : t("export.downloadZip")}
              </span>
            </Button>
          </div>
        </div>

        <p className="text-[10px] text-muted-foreground">
          {activeExport.label} · {t("export.packPhotos", { count: String(packSize) })}
        </p>
      </form>
    </section>
  )
}

export { PromptBar }
export type { PromptBarProps, ExportFormat }
