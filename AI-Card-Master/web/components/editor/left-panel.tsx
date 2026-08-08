"use client"

import {
  Droplets,
  Eye,
  EyeOff,
  ImagePlus,
  Layers,
  Leaf,
  Loader2,
  Lock,
  Package,
  Scissors,
  Shield,
  Sparkles,
  SquareStack,
  Star,
  Type,
  Unlock,
  Upload,
  type LucideIcon,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { ImageWithSkeleton } from "@/components/ui/image-with-skeleton"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { removeBackground } from "@/lib/api"
import {
  BADGE_PRESETS,
  ICON_PRESETS,
  TEXT_PRESETS,
} from "@/lib/constants/mock-editor"
import { useEditorStore } from "@/lib/store/editor-store"
import type { CanvasLayer, CanvasLayerType } from "@/types/canvas"
import { cn } from "@/lib/utils"

const LAYER_ICON: Record<CanvasLayerType, LucideIcon> = {
  background: SquareStack,
  image: ImagePlus,
  text: Type,
  shape: Sparkles,
}

const ICON_MAP: Record<string, LucideIcon> = {
  icon_drop: Droplets,
  icon_leaf: Leaf,
  icon_shield: Shield,
  icon_star: Star,
  icon_spark: Sparkles,
  icon_box: Package,
}

function LayersList() {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const updateLayer = useEditorStore((s) => s.updateLayer)

  const sorted = [...layers].sort((a, b) => b.zIndex - a.zIndex)

  return (
    <ul className="flex flex-col gap-1" role="listbox" aria-label="Слои">
      {sorted.map((layer) => (
        <LayerRow
          key={layer.id}
          layer={layer}
          selected={layer.id === selectedLayerId}
          onSelect={() => selectLayer(layer.id)}
          onToggleVisible={() =>
            updateLayer(layer.id, { visible: !layer.visible })
          }
          onToggleLock={() => updateLayer(layer.id, { locked: !layer.locked })}
        />
      ))}
    </ul>
  )
}

function LayerRow({
  layer,
  selected,
  onSelect,
  onToggleVisible,
  onToggleLock,
}: {
  layer: CanvasLayer
  selected: boolean
  onSelect: () => void
  onToggleVisible: () => void
  onToggleLock: () => void
}) {
  const Icon = LAYER_ICON[layer.type]

  return (
    <li>
      <div
        role="option"
        aria-selected={selected}
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            onSelect()
          }
        }}
        className={cn(
          "group flex cursor-pointer items-center gap-2 rounded-lg border px-2 py-1.5 transition-colors",
          selected
            ? "border-emerald/40 bg-emerald/10 text-foreground"
            : "border-transparent bg-white/[0.03] text-muted-foreground hover:border-white/10 hover:bg-white/[0.05] hover:text-foreground"
        )}
      >
        <Icon className="size-3.5 shrink-0 opacity-80" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-xs font-medium">
          {layer.name}
        </span>
        <button
          type="button"
          className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          aria-label={layer.visible ? "Скрыть слой" : "Показать слой"}
          onClick={(e) => {
            e.stopPropagation()
            onToggleVisible()
          }}
        >
          {layer.visible ? (
            <Eye className="size-3.5" aria-hidden />
          ) : (
            <EyeOff className="size-3.5" aria-hidden />
          )}
        </button>
        <button
          type="button"
          className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          aria-label={layer.locked ? "Разблокировать" : "Заблокировать"}
          onClick={(e) => {
            e.stopPropagation()
            onToggleLock()
          }}
        >
          {layer.locked ? (
            <Lock className="size-3.5" aria-hidden />
          ) : (
            <Unlock className="size-3.5" aria-hidden />
          )}
        </button>
      </div>
    </li>
  )
}

function PhotoUpload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [localPreview, setLocalPreview] = useState<string | null>(null)
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

  const previewSrc = productPreviewUrl ?? localPreview

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          onFiles(e.dataTransfer.files)
        }}
        className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-copper/35 bg-loft/40 px-4 py-8 text-center transition-colors hover:border-emerald/45 hover:bg-emerald/5"
      >
        <Upload className="size-6 text-emerald" aria-hidden />
        <span className="font-heading text-sm font-medium text-foreground">
          Загрузить фото товара
        </span>
        <span className="text-xs text-muted-foreground">
          PNG, JPG или WebP · drag & drop
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(e) => onFiles(e.target.files)}
      />

      {previewSrc ? (
        <div className="space-y-2">
          <ImageWithSkeleton
            src={previewSrc}
            alt="Превью товара"
            className="aspect-square w-full rounded-xl border border-white/10"
            onLoad={() => {
              if (useEditorStore.getState().busyKind === "loading-image") {
                setBusyKind("idle")
              }
            }}
            onLoadError={() => {
              toast.error("Не удалось загрузить изображение")
              if (useEditorStore.getState().busyKind === "loading-image") {
                setBusyKind("idle")
              }
            }}
          />
          <Button
            type="button"
            variant="outline"
            disabled={removingBg}
            aria-busy={removingBg}
            onClick={handleRemoveBackground}
            className="h-10 w-full gap-2 border-white/12 bg-white/[0.03]"
          >
            {removingBg ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Scissors className="size-4 text-copper" aria-hidden />
            )}
            {removingBg ? "Вырезаем фон…" : "Вырезать фон"}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function EditorLeftPanel() {
  return (
    <aside
      className="flex h-full w-[280px] shrink-0 flex-col border-r border-white/8 bg-loft-surface/90"
      aria-label="Панель инструментов"
    >
      <div className="border-b border-white/8 px-3 py-3">
        <h2 className="font-heading text-sm font-semibold tracking-tight">
          Инструменты
        </h2>
        <p className="text-[11px] text-muted-foreground">
          Слои и элементы карточки
        </p>
      </div>

      <Tabs defaultValue="layers" className="flex min-h-0 flex-1 flex-col gap-0">
        <TabsList
          variant="line"
          className="h-auto w-full shrink-0 flex-wrap justify-start gap-0 border-b border-white/8 px-2 pb-0"
        >
          <TabsTrigger value="layers" className="gap-1 px-2 py-2 text-[11px]">
            <Layers className="size-3.5" aria-hidden />
            Слои
          </TabsTrigger>
          <TabsTrigger value="text" className="gap-1 px-2 py-2 text-[11px]">
            <Type className="size-3.5" aria-hidden />
            Текст
          </TabsTrigger>
          <TabsTrigger value="badges" className="gap-1 px-2 py-2 text-[11px]">
            <SquareStack className="size-3.5" aria-hidden />
            Плашки
          </TabsTrigger>
          <TabsTrigger value="icons" className="gap-1 px-2 py-2 text-[11px]">
            <Sparkles className="size-3.5" aria-hidden />
            Иконки
          </TabsTrigger>
          <TabsTrigger value="photo" className="gap-1 px-2 py-2 text-[11px]">
            <ImagePlus className="size-3.5" aria-hidden />
            Фото
          </TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <TabsContent value="layers" className="mt-0">
            <LayersList />
          </TabsContent>

          <TabsContent value="text" className="mt-0 space-y-2">
            {TEXT_PRESETS.map((preset) => (
              <Button
                key={preset.id}
                type="button"
                variant="outline"
                className="h-auto w-full flex-col items-start gap-0.5 border-white/10 bg-white/[0.03] px-3 py-2.5 text-left"
                onClick={() => toast.message(`Добавлен текст: ${preset.label}`)}
              >
                <span className="text-xs font-medium text-foreground">
                  {preset.label}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {preset.sample}
                </span>
              </Button>
            ))}
          </TabsContent>

          <TabsContent value="badges" className="mt-0 grid grid-cols-2 gap-2">
            {BADGE_PRESETS.map((badge) => (
              <button
                key={badge.id}
                type="button"
                onClick={() => toast.message(`Плашка «${badge.label}»`)}
                className={cn(
                  "rounded-lg border px-2.5 py-3 text-center text-xs font-medium transition-colors",
                  badge.tone === "emerald" &&
                    "border-emerald/35 bg-emerald/15 text-emerald",
                  badge.tone === "copper" &&
                    "border-copper/40 bg-copper/15 text-copper",
                  badge.tone === "amber" &&
                    "border-amber/40 bg-amber/15 text-amber",
                  badge.tone === "sage" &&
                    "border-sage/50 bg-sage/40 text-emerald"
                )}
              >
                {badge.label}
              </button>
            ))}
          </TabsContent>

          <TabsContent value="icons" className="mt-0 grid grid-cols-3 gap-2">
            {ICON_PRESETS.map((icon) => {
              const Icon = ICON_MAP[icon.id] ?? Sparkles
              return (
                <button
                  key={icon.id}
                  type="button"
                  title={icon.label}
                  onClick={() => toast.message(`Иконка «${icon.label}»`)}
                  className="flex flex-col items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-3 text-[10px] text-muted-foreground transition-colors hover:border-emerald/35 hover:bg-emerald/10 hover:text-foreground"
                >
                  <Icon className="size-5 text-copper" aria-hidden />
                  {icon.label}
                </button>
              )
            })}
          </TabsContent>

          <TabsContent value="photo" className="mt-0">
            <PhotoUpload />
          </TabsContent>
        </div>
      </Tabs>
    </aside>
  )
}

export { EditorLeftPanel }
