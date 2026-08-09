"use client"

import { ArrowLeft, Languages, Loader2, Redo2, Save, Undo2 } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { EditorCanvasStage } from "@/components/editor/canvas-stage"
import { EditorSettingsPanel } from "@/components/editor/settings-panel"
import { ErrorBoundary } from "@/components/error-boundary"
import { Button, buttonVariants } from "@/components/ui/button"
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
import { GlassButton } from "@/components/ui/glass-button"
import { Skeleton } from "@/components/ui/skeleton"
import { getApiErrorMessage, getDesign, saveDesign } from "@/lib/api"
import {
  canvasStateToLayers,
  createEditorDocument,
  editorDocumentToState,
  layersToCanvasState,
} from "@/lib/editor/editor-document"
import { useI18n, type Locale } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"
import type { EditorProductData } from "@/types/editor"

type EditorWorkspaceProps = {
  projectId: string
  /** Resolved product/card data — Canvas & PromptBar wait until this is present. */
  productData: EditorProductData | null
}

function EditorWorkspace({ projectId, productData }: EditorWorkspaceProps) {
  const { t, locale, setLocale } = useI18n()
  const router = useRouter()
  const setProjectId = useEditorStore((s) => s.setProjectId)
  const loadProject = useEditorStore((s) => s.loadProject)
  const reset = useEditorStore((s) => s.reset)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const setProductPreviewUrl = useEditorStore((s) => s.setProductPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)
  const canUndo = useEditorStore((s) => s.canUndo)
  const canRedo = useEditorStore((s) => s.canRedo)
  const undo = useEditorStore((s) => s.undo)
  const redo = useEditorStore((s) => s.redo)
  const layers = useEditorStore((s) => s.layers)
  const pages = useEditorStore((s) => s.pages)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const softbox = useEditorStore((s) => s.softbox)
  const [saving, setSaving] = useState(false)
  const [remoteDesign, setRemoteDesign] = useState<{
    id: string
    title: string
  } | null>(null)
  const isSavedDesignId =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      projectId
    )
  const loadingProject =
    isSavedDesignId && remoteDesign?.id !== projectId

  useEffect(() => {
    const controller = new AbortController()
    const cutout = productData?.productImage ?? productData?.previewImage ?? null

    reset()
    setProjectId(projectId)
    if (cutout) setProductPreviewUrl(cutout)

    if (!isSavedDesignId) {
      return () => controller.abort()
    }

    void getDesign(projectId, controller.signal)
      .then((design) => {
        if (controller.signal.aborted) return
        setRemoteDesign({ id: design.id, title: design.title })
        if (design.editor_document) {
          const restored = editorDocumentToState(design.editor_document)
          loadProject({
            projectId: design.id,
            ...restored,
            packSize: restored.pages.length,
          })
          return
        }
        const restoredLayers = canvasStateToLayers(design.canvas)
        loadProject({
          projectId: design.id,
          pages: [restoredLayers],
          activePageIndex: 0,
          softbox: useEditorStore.getState().softbox,
          productPreviewUrl: design.preview_url ?? cutout,
          packSize: 1,
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setRemoteDesign({ id: projectId, title: productData?.title ?? projectId })
        toast.error(getApiErrorMessage(error, "Не удалось загрузить проект"))
      })

    return () => controller.abort()
  }, [
    isSavedDesignId,
    loadProject,
    productData?.previewImage,
    productData?.productImage,
    productData?.title,
    projectId,
    reset,
    setProductPreviewUrl,
    setProjectId,
  ])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return
      }
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return
      if (event.key.toLowerCase() !== "z") return
      event.preventDefault()
      if (event.shiftKey) {
        redo()
      } else {
        undo()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [redo, undo])

  const title =
    remoteDesign?.id === projectId
      ? remoteDesign.title
      : (productData?.title ?? `Проект ${projectId}`)
  const isSaving = saving || busyKind === "saving"

  /** Avoid mounting canvas/prompt until product payload + editor store are ready. */
  const canRenderEditorSurface =
    Boolean(productData?.id) &&
    Array.isArray(layers) &&
    layers.length > 0 &&
    softbox != null

  const handleSave = async () => {
    if (isSaving) return
    setSaving(true)
    setBusyKind("saving")
    try {
      const editorDocument = createEditorDocument({
        pages,
        activePageIndex,
        productPreviewUrl,
        softbox,
      })
      const saved = await saveDesign({
        id:
          /^[0-9a-f-]{36}$/i.test(projectId) && projectId !== "new"
            ? projectId
            : null,
        title,
        preview_url: productPreviewUrl,
        canvas: layersToCanvasState(
          pages[activePageIndex] ?? layers,
          productPreviewUrl
        ),
        editor_document: editorDocument,
      })
      setProjectId(saved.id)
      setRemoteDesign({ id: saved.id, title: saved.title })
      if (saved.id !== projectId) {
        router.replace(`/editor/${saved.id}`)
      }
      toast.success(t("editor.saved"))
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.saveError")))
    } finally {
      setSaving(false)
      setBusyKind("idle")
    }
  }

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-transparent text-foreground">
      <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-white/8 bg-loft-surface/95 px-3 backdrop-blur-sm sm:px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/projects"
            className={cn(
              buttonVariants({ size: "icon-sm", variant: "ghost" }),
              "shrink-0 text-muted-foreground"
            )}
            aria-label={t("editor.backToProjects")}
          >
            <ArrowLeft className="size-4" aria-hidden />
          </Link>
          <BrandLogo href="/projects" className="hidden sm:flex" />
          <div className="min-w-0 border-l border-white/10 pl-3">
            <p className="truncate font-heading text-sm font-semibold tracking-tight">
              {title}
            </p>
            <p className="truncate font-mono text-[10px] text-muted-foreground">
              {projectId}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div className="hidden items-center gap-1 sm:flex">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={!canUndo}
              onClick={undo}
              aria-label="Отменить изменение"
              title="Отменить (Ctrl+Z)"
            >
              <Undo2 className="size-4" aria-hidden />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={!canRedo}
              onClick={redo}
              aria-label="Повторить изменение"
              title="Повторить (Ctrl+Shift+Z)"
            >
              <Redo2 className="size-4" aria-hidden />
            </Button>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-sm text-muted-foreground transition-colors",
                "hover:bg-white/8 hover:text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              )}
              aria-label={t("topBar.languageSwitch")}
            >
              <Languages className="size-4" aria-hidden />
              <span className="uppercase">{locale}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-36">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{t("common.language")}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuRadioGroup
                  value={locale}
                  onValueChange={(value) => setLocale(value as Locale)}
                >
                  <DropdownMenuRadioItem value="ru">
                    {t("topBar.russian")}
                  </DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="en">
                    {t("topBar.english")}
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          <GlassButton
            type="button"
            size="sm"
            disabled={isSaving || !canRenderEditorSurface}
            aria-busy={isSaving}
            onClick={handleSave}
          >
            {isSaving ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Save className="size-4" aria-hidden />
            )}
            {isSaving ? t("editor.saving") : t("editor.save")}
          </GlassButton>
        </div>
      </header>

      {canRenderEditorSurface && !loadingProject ? (
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div className="mx-auto flex h-full w-full max-w-7xl min-w-0 flex-col lg:flex-row lg:items-stretch lg:justify-center">
            <ErrorBoundary
              title="Ошибка холста"
              description="Рендер редактора прерван. Состояние проекта сохранено в памяти — попробуйте снова."
              className="min-h-0 min-w-0 flex-1"
            >
              <EditorCanvasStage />
            </ErrorBoundary>
            <EditorSettingsPanel projectTitle={title} />
          </div>
        </div>
      ) : (
        <div
          className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-6"
          role="status"
          aria-live="polite"
        >
          <Skeleton className="h-40 w-32 rounded-xl" />
          <p className="text-sm text-muted-foreground">
            {!productData
              ? t("editor.productUnavailable")
              : t("editor.initializing")}
          </p>
          {!productData ? (
            <Link
              href="/projects"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              {t("editor.returnToProjects")}
            </Link>
          ) : null}
        </div>
      )}
    </div>
  )
}

export { EditorWorkspace }
export type { EditorWorkspaceProps }
