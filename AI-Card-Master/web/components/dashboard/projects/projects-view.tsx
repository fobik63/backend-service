"use client"

import { useDeferredValue, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { ProjectCard } from "@/components/dashboard/projects/project-card"
import { ProjectsEmptyState } from "@/components/dashboard/projects/projects-empty-state"
import { ProjectsGridSkeleton } from "@/components/dashboard/projects/projects-skeleton"
import {
  ProjectsToolbar,
  type MarketplaceFilter,
} from "@/components/dashboard/projects/projects-toolbar"
import { InlineError } from "@/components/ui/state-panel"
import {
  type Project,
} from "@/lib/constants/mock-projects"
import {
  deleteDesign,
  getApiErrorMessage,
  listDesigns,
} from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import type { SavedDesignDTO } from "@/types/api"

function designToProject(design: SavedDesignDTO): Project {
  return {
    id: design.id,
    title: design.title,
    marketplace: null,
    status: "ready",
    createdAt: design.updated_at,
    previewImage: design.preview_url ?? null,
    productImage:
      design.editor_document?.product_preview_url ??
      design.preview_url ??
      undefined,
    accentLabel: "AI",
    editorDocument: design.editor_document,
  }
}

function ProjectsView() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [marketplace, setMarketplace] = useState<MarketplaceFilter>("all")
  const [reloadKey, setReloadKey] = useState(0)
  const [deletingIds, setDeletingIds] = useState<Set<string>>(() => new Set())
  const deferredQuery = useDeferredValue(query)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const result = await listDesigns()
        if (cancelled) return
        setProjects(result.items.map(designToProject))
      } catch (error) {
        if (cancelled) return
        const message = getApiErrorMessage(error, t("projects.loadError"))
        setLoadError(message)
        toast.error(message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [reloadKey, t])

  const filtered = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase()
    return projects.filter((project) => {
      const matchesMarketplace =
        marketplace === "all" || project.marketplace === marketplace
      const matchesQuery =
        q.length === 0 || project.title.toLowerCase().includes(q)
      return matchesMarketplace && matchesQuery
    })
  }, [projects, marketplace, deferredQuery])

  const resetFilters = () => {
    setQuery("")
    setMarketplace("all")
  }

  const handleDelete = async (id: string): Promise<void> => {
    const project = projects.find((item) => item.id === id)
    if (
      !window.confirm(
        project
          ? `Удалить проект «${project.title}» без возможности восстановления?`
          : "Удалить проект без возможности восстановления?"
      )
    ) {
      return
    }
    setDeletingIds((current) => new Set(current).add(id))
    try {
      await deleteDesign(id)
      setProjects((prev) => prev.filter((item) => item.id !== id))
      toast.message(
        project
          ? `${t("projects.deleted")}: ${project.title}`
          : t("projects.deleted")
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("projects.loadError")))
    } finally {
      setDeletingIds((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })
    }
  }

  return (
    <section className="mx-auto w-full max-w-7xl min-w-0 space-y-6 overflow-x-hidden">
      <header className="min-w-0 space-y-1.5">
        <h1 className="font-heading truncate text-2xl font-semibold tracking-tight">
          {t("projects.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("projects.subtitle")}</p>
      </header>

      <ProjectsToolbar
        query={query}
        onQueryChange={setQuery}
        marketplace={marketplace}
        onMarketplaceChange={setMarketplace}
      />

      {loading ? (
        <ProjectsGridSkeleton />
      ) : loadError ? (
        <InlineError
          message={loadError}
          retryLabel={t("projects.showLocal")}
          onRetry={() => {
            setReloadKey((value) => value + 1)
          }}
        />
      ) : filtered.length === 0 ? (
        <ProjectsEmptyState
          hasNoProjects={projects.length === 0}
          onResetFilters={
            projects.length > 0 ? resetFilters : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((project, index) => (
            <ProjectCard
              key={project.id}
              project={project}
              index={index}
              onDelete={handleDelete}
              deleting={deletingIds.has(project.id)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

export { ProjectsView }
