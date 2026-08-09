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
import Image from "next/image"
import { useEffect, useRef, useState, type FormEvent } from "react"
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
  downloadCurrentCanvasImage,
  findEditorExportCanvas,
} from "@/lib/export/card-pack"
import { captureFabricPagesPngBytes } from "@/lib/editor/fabric-export"
import { generateByPrompt, getApiErrorMessage } from "@/lib/api"
import {
  canvasStateToLayers,
  layersToCanvasState,
} from "@/lib/editor/editor-document"
import {
  delay,
  getMockGenerateLayers,
  IS_MOCK,
  MOCK_CARD_IMAGE,
  MOCK_GENERATE_DELAY_MS,
  MOCK_PRODUCT_IMAGE,
  MOCK_SEO_RESULT,
  type MockSeoResult,
} from "@/lib/constants/mock"
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

function MockSeoPreview({ result }: { result: MockSeoResult }) {
  return (
    <div className="space-y-2.5 rounded-xl border border-white/12 bg-white/[0.03] p-3">
      <div className="flex items-start gap-2.5">
        <div className="relative h-14 w-11 shrink-0 overflow-hidden rounded-md border border-white/10">
          <Image
            src={MOCK_CARD_IMAGE}
            alt="Mock card preview"
            fill
            className="object-cover"
            sizes="44px"
          />
        </div>
        <div className="min-w-0 space-y-1">
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            Mock SEO результат
          </p>
          <p className="text-xs font-semibold leading-snug text-foreground">
            {result.optimized_title}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {result.benefits.map((benefit) => (
          <span
            key={benefit}
            className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-0.5 text-[10px] text-muted-foreground"
          >
            {benefit}
          </span>
        ))}
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {result.description}
      </p>
    </div>
  )
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
  const [mockSeo, setMockSeo] = useState<MockSeoResult | null>(null)

  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const setBusyProgress = useEditorStore((s) => s.setBusyProgress)
  const applyGenerationResult = useEditorStore((s) => s.applyGenerationResult)
  const commitActivePage = useEditorStore((s) => s.commitActivePage)
  const storeProjectId = useEditorStore((s) => s.projectId)
  const layers = useEditorStore((s) => s.layers)
  const softbox = useEditorStore((s) => s.softbox)
  const storePreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const backgroundPreviewUrl = useEditorStore((s) => s.backgroundPreviewUrl)
  const packSize = useEditorStore((s) => s.packSize)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const mockRafRef = useRef(0)

  useEffect(() => {
    return () => {
      if (mockRafRef.current) {
        window.cancelAnimationFrame(mockRafRef.current)
        mockRafRef.current = 0
      }
    }
  }, [])

  useEffect(() => {
    const onSeedPrompt = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail
      if (typeof detail === "string" && detail.trim()) {
        setPrompt(detail.trim())
      }
    }
    window.addEventListener("editor:seed-prompt", onSeedPrompt)
    return () => window.removeEventListener("editor:seed-prompt", onSeedPrompt)
  }, [])

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

  const runMockGenerate = async () => {
    setBusyProgress(0)
    const started = performance.now()

    const tick = () => {
      const elapsed = performance.now() - started
      const pct = Math.min(99, (elapsed / MOCK_GENERATE_DELAY_MS) * 100)
      setBusyProgress(pct)
      if (elapsed < MOCK_GENERATE_DELAY_MS) {
        mockRafRef.current = window.requestAnimationFrame(tick)
      } else {
        mockRafRef.current = 0
      }
    }
    mockRafRef.current = window.requestAnimationFrame(tick)

    await delay(MOCK_GENERATE_DELAY_MS)
    if (mockRafRef.current) {
      window.cancelAnimationFrame(mockRafRef.current)
      mockRafRef.current = 0
    }
    setBusyProgress(100)

    // One store write → one undo step → one Fabric scene rebuild.
    applyGenerationResult({
      layers: getMockGenerateLayers(),
      productPreviewUrl: MOCK_PRODUCT_IMAGE,
      backgroundPreviewUrl: MOCK_CARD_IMAGE,
    })
    setMockSeo(MOCK_SEO_RESULT)
    toast.success(t("editor.generateSuccess"))
  }

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
      if (IS_MOCK) {
        await runMockGenerate()
      } else {
        setBusyProgress(null)
        const generated = await generateByPrompt(
          trimmed,
          layersToCanvasState(layers, storePreviewUrl, backgroundPreviewUrl),
        )
        applyGenerationResult({
          layers: canvasStateToLayers(generated),
          backgroundPreviewUrl: generated.background_image_url
            ? generated.background_image_url
            : undefined,
        })
        toast.success(t("editor.generateSuccess"))
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.generateError")))
      setBusyKind("idle")
      setBusyProgress(null)
    } finally {
      setGenerating(false)
      // Keep busy overlay until Fabric finishes rebuilding the scene
      // (fabric-canvas clears busyKind on successful rebuild). Safety timeout:
      window.setTimeout(() => {
        const kind = useEditorStore.getState().busyKind
        if (kind === "generating") {
          useEditorStore.getState().setBusyKind("idle")
          useEditorStore.getState().setBusyProgress(null)
        }
      }, 8_000)
    }
  }

  const handleExport = async (format: ExportFormat = exportFormat) => {
    if (exporting) return
    setExportFormat(format)
    setExporting(true)
    try {
      const pageNum = activePageIndex + 1
      const safeBase =
        zipTitle.replace(/[^\w\-а-яё]+/gi, "-").replace(/^-+|-+$/g, "") ||
        "card"
      const filename =
        format === "webp"
          ? `${safeBase}-page-${pageNum}.webp`
          : `${safeBase}-page-${pageNum}.png`

      await downloadCurrentCanvasImage({
        canvasEl: findEditorExportCanvas(),
        filename,
        format,
      })
      toast.success(
        t("editor.downloadCurrentSuccess", {
          n: String(pageNum),
          format: format === "png" ? "PNG" : "WebP",
        }),
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.downloadCurrentError")))
    } finally {
      setExporting(false)
    }
  }

  const handleZip = async () => {
    if (zipping) return
    setZipping(true)
    try {
      commitActivePage()
      const store = useEditorStore.getState()
      const latestPages = store.pages
      const pageSnapshot = latestPages.map((page) =>
        page.map((layer) => ({
          ...layer,
          textStyle: layer.textStyle ? { ...layer.textStyle } : undefined,
          chip: layer.chip ? { ...layer.chip } : undefined,
        })),
      )

      // Prefer live Fabric captures (1080×1440, no selection chrome / guides).
      let fabricPages: Uint8Array[] | null = null
      try {
        fabricPages = await captureFabricPagesPngBytes({
          pageCount: Math.min(packSize, latestPages.length),
          getActivePageIndex: () => useEditorStore.getState().activePageIndex,
          setActivePageIndex: (index) =>
            useEditorStore.getState().setActivePageIndex(index),
        })
      } catch {
        fabricPages = null
      }

      await downloadCardPackZip({
        packSize,
        projectTitle: zipTitle,
        productImageUrl: storePreviewUrl,
        layers,
        pages: pageSnapshot,
        softbox: { ...softbox },
        zipBasename: zipTitle,
        capturePageAtIndex: fabricPages
          ? async (pageIndex) => {
              const hit = fabricPages![pageIndex]
              if (hit) return hit
              // Pack larger than editor pages — fall back to last captured page.
              return fabricPages![fabricPages!.length - 1]!
            }
          : undefined,
      })
      toast.success(
        t("export.success", {
          count: String(packSize),
        }),
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
          "shrink-0 border-t border-zinc-800/80 bg-zinc-900/60 backdrop-blur-xl",
          className,
        )}
        aria-label={t("editor.promptBarAria")}
      >
        <form
          onSubmit={handleGenerate}
          className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:gap-3 sm:px-4"
        >
          <div className="relative min-w-0 flex-1">
            <Sparkles
              className="pointer-events-none absolute top-3 left-3 size-4 text-muted-foreground"
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
                "min-h-12 resize-none border-white/10 bg-loft pl-10 text-sm",
                "placeholder:text-muted-foreground/70",
                "focus-visible:border-white/25 focus-visible:ring-white/15",
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
        {IS_MOCK && mockSeo ? (
          <div className="border-t border-white/8 px-3 py-3 sm:px-4">
            <MockSeoPreview result={mockSeo} />
          </div>
        ) : null}
      </footer>
    )
  }

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label={t("editor.promptBarAria")}
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.promptSection")}
        </h3>
        {IS_MOCK ? (
          <span className="rounded border border-white/12 bg-white/[0.04] px-2 py-0.5 text-[10px] text-muted-foreground">
            MOCK
          </span>
        ) : null}
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
            "min-h-[4.5rem] resize-none border-white/10 bg-white/[0.03] text-xs leading-relaxed",
            "placeholder:text-muted-foreground/70",
            "focus-visible:border-white/25 focus-visible:ring-white/15",
          )}
        />

        <div className="grid grid-cols-1 gap-2">
          <GlassButton
            type="submit"
            size="sm"
            disabled={generating || !prompt.trim() || busy}
            className={cn("w-full", generating && "opacity-90")}
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
                  "hover:bg-white/8 hover:text-foreground",
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
                    "disabled:pointer-events-none disabled:opacity-50",
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
                            selected && "bg-white/10 text-foreground",
                          )}
                        >
                          <Icon
                            className={cn(
                              "size-4",
                              selected ? "text-emerald" : "text-muted-foreground",
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

      {IS_MOCK && mockSeo ? <MockSeoPreview result={mockSeo} /> : null}
    </section>
  )
}

export { PromptBar }
export type { PromptBarProps, ExportFormat }
