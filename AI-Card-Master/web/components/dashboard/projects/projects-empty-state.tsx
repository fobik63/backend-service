"use client"

import { Leaf, Plus } from "lucide-react"
import Link from "next/link"
import { motion } from "framer-motion"

import { GlassButton, glassButtonVariants } from "@/components/ui/glass-button"
import { GlassCard } from "@/components/ui/glass-card"
import { cn } from "@/lib/utils"

type ProjectsEmptyStateProps = {
  /** True when the user has no projects at all (vs. empty filter results) */
  hasNoProjects: boolean
  onResetFilters?: () => void
}

function ProjectsEmptyState({
  hasNoProjects,
  onResetFilters,
}: ProjectsEmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <GlassCard
        hoverLift={false}
        padding="lg"
        className="relative overflow-hidden border-dashed border-white/15"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,rgba(16,185,129,0.12),transparent_55%),radial-gradient(ellipse_at_80%_90%,rgba(194,166,140,0.08),transparent_50%)]"
        />

        <div className="relative mx-auto flex max-w-md flex-col items-center gap-5 py-8 text-center sm:py-12">
          <div className="relative">
            <span
              aria-hidden
              className="absolute inset-0 rounded-full bg-emerald/20 blur-xl"
            />
            <span className="relative flex size-16 items-center justify-center rounded-2xl border border-emerald/25 bg-sage/40 text-emerald shadow-[0_0_28px_rgba(16,185,129,0.18)]">
              <Leaf className="size-8" strokeWidth={1.5} />
            </span>
          </div>

          {hasNoProjects ? (
            <>
              <div className="space-y-2">
                <h2 className="font-heading text-xl font-semibold tracking-tight">
                  Здесь пока тихо
                </h2>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Создайте первую карточку товара — AI-Card Master соберёт
                  превью под Ozon или Wildberries и сохранит проект здесь.
                </p>
              </div>
              <Link
                href="/dashboard/create"
                className={cn(glassButtonVariants({ size: "lg" }), "gap-2")}
              >
                <Plus className="size-5" aria-hidden />
                Создать первую карточку
              </Link>
            </>
          ) : (
            <>
              <div className="space-y-2">
                <h2 className="font-heading text-xl font-semibold tracking-tight">
                  Ничего не найдено
                </h2>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Попробуйте изменить поиск или фильтр маркетплейса.
                </p>
              </div>
              {onResetFilters ? (
                <GlassButton size="default" onClick={onResetFilters}>
                  Сбросить фильтры
                </GlassButton>
              ) : null}
            </>
          )}
        </div>
      </GlassCard>
    </motion.div>
  )
}

export { ProjectsEmptyState }
export type { ProjectsEmptyStateProps }
