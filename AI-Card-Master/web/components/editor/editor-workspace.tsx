"use client"

import { ArrowLeft, Languages, Loader2, Save } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { EditorCanvasStage } from "@/components/editor/canvas-stage"
import { EditorSettingsPanel } from "@/components/editor/settings-panel"
import { buttonVariants } from "@/components/ui/button"
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
import { getApiErrorMessage } from "@/lib/api"
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
  const setProjectId = useEditorStore((s) => s.setProjectId)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const setProductPreviewUrl = useEditorStore((s) => s.setProductPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)
  const layers = useEditorStore((s) => s.layers)
  const softbox = useEditorStore((s) => s.softbox)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setProjectId(projectId)
  }, [projectId, setProjectId])

  useEffect(() => {
    const cutout =
      productData?.productImage ?? productData?.previewImage ?? null
    if (cutout) {
      setProductPreviewUrl(cutout)
    }
  }, [
    productData?.productImage,
    productData?.previewImage,
    setProductPreviewUrl,
  ])

  const title = productData?.title ?? `Проект ${projectId}`
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
      await new Promise((r) => setTimeout(r, 700))
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

      {canRenderEditorSurface ? (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Canvas + params centered as one work block */}
          <div className="mx-auto flex h-full w-full max-w-7xl min-w-0 items-center justify-center">
            <EditorCanvasStage />
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
