"use client"

import {
  Loader2,
  Scissors,
  Type,
  Upload,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
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
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

function CanvasToolbar({ className }: { className?: string }) {
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
      toast.error("Выберите изображение")
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
      toast.error("Не удалось вырезать фон")
    } finally {
      setBusyKind("idle")
    }
  }

  return (
    <div
      className={cn(
        "pointer-events-auto absolute top-3 left-3 z-20 flex flex-wrap items-center gap-1.5",
        className
      )}
      role="toolbar"
      aria-label="Действия на холсте"
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(e) => onFiles(e.target.files)}
      />

      <Button
        type="button"
        size="sm"
        variant="secondary"
        className="h-8 gap-1.5 border border-white/12 bg-loft-surface/95 shadow-lg backdrop-blur-sm"
        onClick={() => inputRef.current?.click()}
      >
        <Upload className="size-3.5" aria-hidden />
        Фото
      </Button>

      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={removingBg || (!pendingFile && !productPreviewUrl)}
        aria-busy={removingBg}
        className="h-8 gap-1.5 border border-white/12 bg-loft-surface/95 shadow-lg backdrop-blur-sm"
        onClick={() => void handleRemoveBackground()}
      >
        {removingBg ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <Scissors className="size-3.5" aria-hidden />
        )}
        Фон
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/12 bg-loft-surface/95 px-2.5 text-sm shadow-lg backdrop-blur-sm",
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
    </div>
  )
}

export { CanvasToolbar }
