"use client"

import { ArrowLeft, Loader2, Save, Upload } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState, type MouseEvent } from "react"
import { toast } from "sonner"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { EditorAiPanel } from "@/components/editor/ai-panel"
import { EditorCanvasStage } from "@/components/editor/canvas-stage"
import { ImportPublishDialog } from "@/components/editor/import-publish-dialog"
import { EditorSettingsPanel } from "@/components/editor/settings-panel"
import { ErrorBoundary } from "@/components/error-boundary"
import { Button, buttonVariants } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { Skeleton } from "@/components/ui/skeleton"
import { getApiErrorMessage, getDesign, saveDesign } from "@/lib/api"
import {
  canvasStateToLayers,
  createEditorDocument,
  layersToCanvasState,
  tryEditorDocumentToState,
} from "@/lib/editor/editor-document"
import { getActiveFabricCanvas } from "@/lib/editor/fabric-export"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"
import type { EditorProductData } from "@/types/editor"

type EditorWorkspaceProps = {
  projectId: string
  /** Resolved product/card data — Canvas & PromptBar wait until this is present. */
  productData: EditorProductData | null
}

/** Exit editor via full page load — Soft Router + Fabric dispose can freeze the UI. */
function leaveEditorToHome(event: MouseEvent<HTMLAnchorElement>) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }
  event.preventDefault()
  window.location.assign("/projects")
}

function EditorWorkspace({ projectId, productData }: EditorWorkspaceProps) {
  const { t } = useI18n()
  const router = useRouter()
  const setProjectId = useEditorStore((s) => s.setProjectId)
  const loadProject = useEditorStore((s) => s.loadProject)
  const reset = useEditorStore((s) => s.reset)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const setProductPreviewUrl = useEditorStore((s) => s.setProductPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)
  const undo = useEditorStore((s) => s.undo)
  const redo = useEditorStore((s) => s.redo)
  const layers = useEditorStore((s) => s.layers)
  const pages = useEditorStore((s) => s.pages)
  const activePageIndex = useEditorStore((s) => s.activePageIndex)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const backgroundPreviewUrl = useEditorStore((s) => s.backgroundPreviewUrl)
  const softbox = useEditorStore((s) => s.softbox)
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [remoteDesign, setRemoteDesign] = useState<{
    id: string
    title: string
  } | null>(null)
  /** Saved UUID designs stay gated until getDesign + loadProject succeed. */
  const [hydrateStatus, setHydrateStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle")
  const isSavedDesignId =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      projectId
    )

  useEffect(() => {
    const controller = new AbortController()
    const cutout = productData?.productImage ?? productData?.previewImage ?? null
    const isNewCard = projectId === "new"

    // New card: wipe Zustand + Fabric so prior project layers/history cannot linger.
    if (isNewCard) {
      reset({ blank: true })
      setProjectId(projectId)
      queueMicrotask(() => {
        if (!controller.signal.aborted) {
          setRemoteDesign(null)
          setHydrateStatus("ready")
        }
      })
      const canvas = getActiveFabricCanvas()
      if (canvas) {
        canvas.clear()
        canvas.backgroundColor = "#0d0f12"
        canvas.requestRenderAll()
      }
      return () => controller.abort()
    }

    // UUID designs: blank shell until remote doc restores (never flash mock pack).
    if (isSavedDesignId) {
      reset({ blank: true })
      setProjectId(projectId)
      setHydrateStatus("loading")
      if (cutout) setProductPreviewUrl(cutout)

      void getDesign(projectId, controller.signal)
        .then((design) => {
          if (controller.signal.aborted) return
          setRemoteDesign({ id: design.id, title: design.title })

          const fromDoc = design.editor_document
            ? tryEditorDocumentToState(design.editor_document)
            : null
          if (fromDoc) {
            loadProject({
              projectId: design.id,
              ...fromDoc,
              productPreviewUrl:
                fromDoc.productPreviewUrl ?? design.preview_url ?? cutout,
              packSize: fromDoc.pages.length,
            })
            setHydrateStatus("ready")
            return
          }

          const restoredLayers = canvasStateToLayers(design.canvas)
          loadProject({
            projectId: design.id,
            pages: [restoredLayers],
            activePageIndex: 0,
            softbox: useEditorStore.getState().softbox,
            productPreviewUrl: design.preview_url ?? cutout,
            backgroundPreviewUrl: design.canvas.background_image_url ?? null,
            packSize: 1,
          })
          setHydrateStatus("ready")
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          if (
            (typeof DOMException !== "undefined" &&
              error instanceof DOMException &&
              error.name === "AbortError") ||
            (error instanceof Error && error.name === "AbortError")
          ) {
            return
          }
          setHydrateStatus("error")
          setRemoteDesign({
            id: projectId,
            title: productData?.title ?? projectId,
          })
          toast.error(getApiErrorMessage(error, "Не удалось загрузить проект"))
        })

      return () => controller.abort()
    }

    // Sandbox / non-UUID ids: local mock pack is fine.
    reset()
    setProjectId(projectId)
    setHydrateStatus("ready")
    if (cutout) setProductPreviewUrl(cutout)

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
      const key = event.key.toLowerCase()
      if (key === "y") {
        event.preventDefault()
        redo()
        return
      }
      if (key !== "z") return
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

  /** Gate Fabric until this projectId is fully hydrated (no cross-project flash). */
  const surfaceReady =
    hydrateStatus === "ready" &&
    (!isSavedDesignId || remoteDesign?.id === projectId)

  /** Avoid mounting canvas/prompt until product payload + editor store are ready. */
  const canRenderEditorSurface =
    Boolean(productData?.id) &&
    Array.isArray(layers) &&
    softbox != null &&
    surfaceReady

  const handleSave = async () => {
    if (isSaving) return
    setSaving(true)
    setBusyKind("saving")
    try {
      const editorDocument = createEditorDocument({
        pages,
        activePageIndex,
        productPreviewUrl,
        backgroundPreviewUrl,
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
          productPreviewUrl,
          backgroundPreviewUrl
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
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-transparent text-foreground">
      <div className="relative z-20 flex h-12 shrink-0 items-center justify-between gap-3 border-b border-zinc-800/60 bg-zinc-900/40 px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <Link
            href="/projects"
            onClick={leaveEditorToHome}
            className={cn(
              buttonVariants({ size: "sm", variant: "ghost" }),
              "shrink-0 gap-1.5 px-2 text-muted-foreground hover:text-foreground"
            )}
            aria-label={t("editor.backToProjects")}
          >
            <ArrowLeft className="size-4 shrink-0" aria-hidden />
            <span className="max-w-[11rem] truncate sm:max-w-none">
              {t("editor.backToProjects")}
            </span>
          </Link>
          <BrandLogo
            href="/projects"
            onClick={leaveEditorToHome}
            className="hidden border-l border-white/10 pl-3 sm:flex"
          />
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="hidden gap-1.5 border-white/12 sm:inline-flex"
            disabled={!canRenderEditorSurface}
            onClick={() => setImportOpen(true)}
          >
            <Upload className="size-3.5" aria-hidden />
            Импорт и Постинг
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="sm:hidden"
            disabled={!canRenderEditorSurface}
            onClick={() => setImportOpen(true)}
            aria-label="Импорт и Постинг"
          >
            <Upload className="size-4" aria-hidden />
          </Button>

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
      </div>

      <ImportPublishDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        projectTitle={title}
      />

      {canRenderEditorSurface ? (
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div className="flex h-full w-full min-w-0 flex-col gap-3 overflow-hidden p-3 lg:flex-row lg:items-stretch">
            <EditorAiPanel projectTitle={title} />
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
          className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-hidden px-6"
          role="status"
          aria-live="polite"
        >
          {hydrateStatus === "error" ? (
            <>
              <p className="max-w-sm text-center text-sm text-muted-foreground">
                Не удалось загрузить проект. Вернитесь к списку и откройте карточку снова.
              </p>
              <Link
                href="/projects"
                onClick={leaveEditorToHome}
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              >
                {t("editor.returnToProjects")}
              </Link>
            </>
          ) : (
            <>
              <Skeleton className="h-40 w-32 rounded-xl" />
              <p className="text-sm text-muted-foreground">
                {!productData
                  ? t("editor.productUnavailable")
                  : t("editor.initializing")}
              </p>
              {!productData ? (
                <Link
                  href="/projects"
                  onClick={leaveEditorToHome}
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                >
                  {t("editor.returnToProjects")}
                </Link>
              ) : (
                <Link
                  href="/projects"
                  onClick={leaveEditorToHome}
                  className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                >
                  {t("editor.backToProjects")}
                </Link>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export { EditorWorkspace }
export type { EditorWorkspaceProps }
