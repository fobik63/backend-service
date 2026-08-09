"use client"

import {
  Download,
  Loader2,
  Scissors,
  Type,
  Upload,
} from "lucide-react"
import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type RefObject,
} from "react"
import { toast } from "sonner"

import { BadgeToolbarMenu } from "@/components/editor/badge-tool"
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
import { removeBackground } from "@/lib/api"
import { TEXT_PRESETS } from "@/lib/constants/mock-editor"
import { addTextPresetToCanvas } from "@/lib/editor/canvas-actions"
import {
  exportFabricCanvasPng,
  FABRIC_EXPORT_PRESETS,
} from "@/lib/editor/fabric-export"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

function useProductPhotoUpload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [localPreview, setLocalPreview] = useState<string | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const setProductPreviewUrl = useEditorStore((s) => s.setProductPreviewUrl)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const busyKind = useEditorStore((s) => s.busyKind)
  const removingBg = busyKind === "removing-bg"

  useEffect(() => {
    return () => {
      if (localPreview?.startsWith("blob:")) {
        URL.revokeObjectURL(localPreview)
      }
    }
  }, [localPreview])

  const onFiles = (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    if (!file.type.startsWith("image/")) {
      toast.error("Выберите изображение (PNG, JPEG или WebP)")
      return
    }

    if (localPreview?.startsWith("blob:")) {
      URL.revokeObjectURL(localPreview)
    }

    const url = URL.createObjectURL(file)
    setPendingFile(file)
    setLocalPreview(url)
    setProductPreviewUrl(url)
    setBusyKind("loading-image")
    toast.success(`Фото «${file.name}» добавлено на холст`)
  }

  const handleRemoveBackground = async () => {
    if (!pendingFile && !productPreviewUrl) {
      toast.error("Сначала загрузите фото товара")
      return
    }
    if (removingBg) return

    setBusyKind("removing-bg")
    try {
      const result = await removeBackground({
        file: pendingFile ?? undefined,
        imageUrl: pendingFile ? undefined : productPreviewUrl ?? undefined,
      })
      setProductPreviewUrl(result.cdn_url)
      toast.success("Фон вырезан")
    } catch {
      toast.error("Не удалось вырезать фон. Проверьте соединение и попробуйте снова.")
    } finally {
      setBusyKind("idle")
    }
  }

  return {
    inputRef,
    productPreviewUrl,
    removingBg,
    onFiles,
    handleRemoveBackground,
    openPicker: () => inputRef.current?.click(),
  }
}

function FileInput({
  inputRef,
  onFiles,
}: {
  inputRef: RefObject<HTMLInputElement | null>
  onFiles: (files: FileList | null) => void
}) {
  return (
    <input
      ref={inputRef}
      type="file"
      accept="image/png,image/jpeg,image/webp"
      className="sr-only"
      onChange={(e) => {
        onFiles(e.target.files)
        e.target.value = ""
      }}
    />
  )
}

function CanvasToolbar({
  className,
  compact = false,
}: {
  className?: string
  /** Photo + cutout only — text/badge/export live in side panels / quick bar. */
  compact?: boolean
}) {
  const {
    inputRef,
    productPreviewUrl,
    removingBg,
    onFiles,
    handleRemoveBackground,
    openPicker,
  } = useProductPhotoUpload()
  const [exporting, setExporting] = useState(false)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const layers = useEditorStore((s) => s.layers)

  const handleExportPng = async (presetIndex = 0) => {
    if (exporting) return
    setExporting(true)
    try {
      const size = FABRIC_EXPORT_PRESETS[presetIndex] ?? FABRIC_EXPORT_PRESETS[0]!
      const title =
        layers.find((l) => l.type === "text" && l.text?.trim())?.text?.trim() ||
        "card"
      const safe = title.replace(/[^\w\-а-яё]+/gi, "-").replace(/^-+|-+$/g, "") || "card"
      await exportFabricCanvasPng({
        size,
        filename: `${safe}-page-${activePageIndex + 1}-${size.width}x${size.height}`,
      })
      toast.success(`Экспорт PNG ${size.label}`)
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Не удалось экспортировать PNG"
      )
    } finally {
      setExporting(false)
    }
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5",
        className
      )}
      role="toolbar"
      aria-label="Действия на холсте"
    >
      <FileInput inputRef={inputRef} onFiles={onFiles} />

      <Button
        type="button"
        size="sm"
        variant="secondary"
        className="h-8 gap-1.5 border border-white/12 bg-loft-surface"
        onClick={openPicker}
      >
        <Upload className="size-3.5" aria-hidden />
        Фото
      </Button>

      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={removingBg || (!productPreviewUrl)}
        aria-busy={removingBg}
        className="h-8 gap-1.5 border border-white/12 bg-loft-surface"
        onClick={() => void handleRemoveBackground()}
      >
        {removingBg ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <Scissors className="size-3.5" aria-hidden />
        )}
        Фон
      </Button>

      {compact ? null : (
        <>
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/12 bg-loft-surface px-2.5 text-sm",
                "text-secondary-foreground outline-none transition-colors hover:bg-secondary/80",
                "focus-visible:ring-2 focus-visible:ring-ring/50"
              )}
            >
              <Type className="size-3.5" aria-hidden />
              Текст
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-48">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Добавить текст</DropdownMenuLabel>
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

          <BadgeToolbarMenu />

          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={exporting}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg border border-emerald/30 bg-emerald/10 px-2.5 text-sm",
                "text-emerald outline-none transition-colors hover:bg-emerald/15",
                "focus-visible:ring-2 focus-visible:ring-ring/50",
                "disabled:pointer-events-none disabled:opacity-50"
              )}
              aria-label="Экспорт PNG"
            >
              {exporting ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Download className="size-3.5" aria-hidden />
              )}
              Экспорт
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-52">
              <DropdownMenuGroup>
                <DropdownMenuLabel>PNG высокого разрешения</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {FABRIC_EXPORT_PRESETS.map((preset, index) => (
                  <DropdownMenuItem
                    key={preset.label}
                    disabled={exporting}
                    onClick={() => void handleExportPng(index)}
                  >
                    <div className="flex flex-col gap-0.5">
                      <span>Экспорт {preset.label}</span>
                      <span className="text-[11px] text-muted-foreground">
                        Слои 1–3 склеены в браузере
                      </span>
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
    </div>
  )
}

function CanvasPhotoDropzone({ className }: { className?: string }) {
  const { inputRef, onFiles, openPicker } = useProductPhotoUpload()
  const [dragging, setDragging] = useState(false)

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(true)
  }

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    onFiles(event.dataTransfer.files)
  }

  return (
    <div
      className={cn(
        "absolute inset-0 z-10 flex items-center justify-center p-4 sm:p-6",
        className
      )}
    >
      <FileInput inputRef={inputRef} onFiles={onFiles} />
      <div
        role="button"
        tabIndex={0}
        onClick={openPicker}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            openPicker()
          }
        }}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          "flex w-full max-w-sm cursor-pointer flex-col items-center gap-3 rounded-xl border border-dashed px-5 py-8 text-center transition-colors",
          dragging
            ? "border-foreground/50 bg-white/[0.06]"
            : "border-white/15 bg-loft-surface/90 hover:border-white/25 hover:bg-loft-surface"
        )}
      >
        <span className="flex size-11 items-center justify-center rounded-lg border border-white/12 text-muted-foreground">
          <Upload className="size-5" strokeWidth={1.5} aria-hidden />
        </span>
        <div className="space-y-1">
          <p className="font-heading text-sm font-semibold tracking-tight">
            Загрузите фото товара
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Перетащите файл сюда или нажмите для выбора.
            <br />
            PNG, JPEG или WebP.
          </p>
        </div>
      </div>
    </div>
  )
}

export { CanvasToolbar, CanvasPhotoDropzone }
