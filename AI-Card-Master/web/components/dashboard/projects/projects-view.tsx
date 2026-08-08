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
import {
  MOCK_PROJECTS,
  type Project,
} from "@/lib/constants/mock-projects"
import { getApiErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/i18n"

function ProjectsView() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [marketplace, setMarketplace] = useState<MarketplaceFilter>("all")
  const deferredQuery = useDeferredValue(query)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setLoadError(null)
      try {
        // Simulate network fetch until projects API is wired.
        await new Promise((r) => setTimeout(r, 650))
        if (cancelled) return
        setProjects(MOCK_PROJECTS)
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
  }, [t])

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

  const handleDelete = (id: string) => {
    const project = projects.find((item) => item.id === id)
    setProjects((prev) => prev.filter((item) => item.id !== id))
    toast.message(
      project
        ? `${t("projects.deleted")}: ${project.title}`
        : t("projects.deleted")
    )
  }

  return (
    <section className="mx-auto w-full max-w-7xl space-y-6">
      <header className="space-y-1.5">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">
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
        <div
          className="rounded-xl border border-amber/30 bg-amber/10 px-4 py-6 text-center"
          role="alert"
        >
          <p className="text-sm text-foreground">{loadError}</p>
          <button
            type="button"
            className="mt-3 text-sm text-emerald underline-offset-4 hover:underline"
            onClick={() => {
              setProjects(MOCK_PROJECTS)
              setLoadError(null)
            }}
          >
            {t("projects.showLocal")}
          </button>
        </div>
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
            />
          ))}
        </div>
      )}
    </section>
  )
}

export { ProjectsView }
