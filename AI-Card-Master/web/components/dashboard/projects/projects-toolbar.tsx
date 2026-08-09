"use client"

import { Plus, Search } from "lucide-react"
import Link from "next/link"

import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { ProjectMarketplace } from "@/lib/constants/mock-projects"

export type MarketplaceFilter = "all" | ProjectMarketplace

type ProjectsToolbarProps = {
  query: string
  onQueryChange: (value: string) => void
  marketplace: MarketplaceFilter
  onMarketplaceChange: (value: MarketplaceFilter) => void
}

const MARKETPLACE_FILTERS: { value: MarketplaceFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "ozon", label: "Ozon" },
  { value: "wb", label: "WB" },
]

function ProjectsToolbar({
  query,
  onQueryChange,
  marketplace,
  onMarketplaceChange,
}: ProjectsToolbarProps) {
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative block w-full max-w-md">
          <span className="sr-only">Поиск по названию карточки</span>
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Поиск по названию…"
            className="h-10 bg-loft-surface pl-9 md:text-sm"
          />
        </label>

        <div
          role="group"
          aria-label="Фильтр по маркетплейсу"
          className="flex shrink-0 items-center gap-1 rounded-lg border border-white/10 bg-loft-surface p-1"
        >
          {MARKETPLACE_FILTERS.map((filter) => {
            const active = marketplace === filter.value
            return (
              <Button
                key={filter.value}
                type="button"
                size="sm"
                variant="ghost"
                aria-pressed={active}
                onClick={() => onMarketplaceChange(filter.value)}
                className={cn(
                  "h-8 min-w-12 px-3",
                  active
                    ? "bg-white/10 text-foreground hover:bg-white/12 hover:text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {filter.label}
              </Button>
            )
          })}
        </div>
      </div>

      <Link
        href="/editor"
        className={cn(
          buttonVariants({ variant: "default", size: "lg" }),
          "h-10 gap-2"
        )}
      >
        <Plus className="size-4" aria-hidden />
        Новый проект
      </Link>
    </div>
  )
}

export { ProjectsToolbar }
export type { ProjectsToolbarProps }
