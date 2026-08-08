"use client"

import {
  ChevronDown,
  Download,
  FileImage,
  ImageIcon,
  Loader2,
  Sparkles,
} from "lucide-react"
import { useState, type FormEvent } from "react"
import { toast } from "sonner"

import { ExportButton } from "@/components/editor/export-button"
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
import { Input } from "@/components/ui/input"
import { getApiErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type ExportFormat = "png" | "webp"

type PromptBarProps = {
  className?: string
  projectTitle?: string
}

function PromptBar({ className, projectTitle }: PromptBarProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState("")
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportFormat, setExportFormat] = useState<ExportFormat>("png")
  const setBusyKind = useEditorStore((s) => s.setBusyKind)

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

  const activeExport =
    exportOptions.find((o) => o.id === exportFormat) ?? exportOptions[0]

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
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-emerald/70"
            aria-hidden
          />
          <Input
            id="editor-ai-prompt"
            value={prompt}
            disabled={generating}
            placeholder={t("editor.promptPlaceholder")}
            aria-label={t("editor.promptAria")}
            onChange={(e) => setPrompt(e.target.value)}
            className={cn(
              "h-12 border-white/10 bg-loft/60 pl-10 text-sm md:text-sm",
              "placeholder:text-muted-foreground/70",
              "focus-visible:border-emerald/40 focus-visible:ring-emerald/25"
            )}
          />
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <GlassButton
            type="submit"
            size="default"
            disabled={generating || !prompt.trim()}
            className={cn(
              "h-12 min-w-[11.5rem] shadow-emerald-glow",
              generating && "opacity-90"
            )}
            aria-busy={generating}
          >
            {generating ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-4" aria-hidden />
            )}
            {generating ? t("editor.generating") : t("editor.generate")}
          </GlassButton>

          <div className="inline-flex h-12 overflow-hidden rounded-lg border border-white/12 bg-loft/50">
            <Button
              type="button"
              variant="ghost"
              disabled={exporting}
              onClick={() => handleExport(exportFormat)}
              className={cn(
                "h-full gap-2 rounded-none px-3 text-sm text-foreground",
                "hover:bg-white/8 hover:text-foreground"
              )}
              aria-busy={exporting}
            >
              {exporting ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Download className="size-4 text-copper" aria-hidden />
              )}
              <span className="hidden sm:inline">
                {exportFormat === "png"
                  ? t("editor.downloadPng")
                  : `${t("editor.download")} ${activeExport.label}`}
              </span>
              <span className="sm:hidden">{t("editor.download")}</span>
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger
                disabled={exporting}
                aria-label={t("editor.exportFormat")}
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
              <DropdownMenuContent align="end" side="top" className="min-w-56">
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

          <ExportButton projectTitle={projectTitle} />
        </div>
      </form>
    </footer>
  )
}

export { PromptBar }
export type { PromptBarProps, ExportFormat }
