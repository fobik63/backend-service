"use client"

import { ArrowLeft, Loader2, Save } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { EditorCanvasStage } from "@/components/editor/canvas-stage"
import { EditorLeftPanel } from "@/components/editor/left-panel"
import { PromptBar } from "@/components/editor/prompt-bar"
import { EditorRightPanel } from "@/components/editor/right-panel"
import { buttonVariants } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { getApiErrorMessage } from "@/lib/api"
import { MOCK_PROJECTS } from "@/lib/constants/mock-projects"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type EditorWorkspaceProps = {
  projectId: string
}

function EditorWorkspace({ projectId }: EditorWorkspaceProps) {
  const setProjectId = useEditorStore((s) => s.setProjectId)
  const setBusyKind = useEditorStore((s) => s.setBusyKind)
  const busyKind = useEditorStore((s) => s.busyKind)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setProjectId(projectId)
  }, [projectId, setProjectId])

  const project = MOCK_PROJECTS.find((p) => p.id === projectId)
  const title = project?.title ?? `Проект ${projectId}`
  const isSaving = saving || busyKind === "saving"

  const handleSave = async () => {
    if (isSaving) return
    setSaving(true)
    setBusyKind("saving")
    try {
      await new Promise((r) => setTimeout(r, 700))
      toast.success("Проект сохранен")
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Не удалось сохранить проект"))
    } finally {
      setSaving(false)
      setBusyKind("idle")
    }
  }

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-loft text-foreground">
      <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-white/8 bg-loft-surface/95 px-3 backdrop-blur-sm sm:px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/projects"
            className={cn(
              buttonVariants({ size: "icon-sm", variant: "ghost" }),
              "shrink-0 text-muted-foreground"
            )}
            aria-label="К проектам"
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

        <GlassButton
          type="button"
          size="sm"
          disabled={isSaving}
          aria-busy={isSaving}
          onClick={handleSave}
        >
          {isSaving ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Save className="size-4" aria-hidden />
          )}
          {isSaving ? "Сохранение…" : "Сохранить"}
        </GlassButton>
      </header>

      <div className="flex min-h-0 flex-1">
        <EditorLeftPanel />
        <EditorCanvasStage />
        <EditorRightPanel />
      </div>

      <PromptBar />
    </div>
  )
}

export { EditorWorkspace }
