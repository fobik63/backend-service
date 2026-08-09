"use client"

import { ImageIcon, Plus } from "lucide-react"
import Link from "next/link"
import { motion } from "framer-motion"

import { GlassButton, glassButtonVariants } from "@/components/ui/glass-button"
import { StatePanel } from "@/components/ui/state-panel"
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
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
    >
      <StatePanel
        icon={ImageIcon}
        title={hasNoProjects ? "Проектов пока нет" : "Ничего не найдено"}
        description={
          hasNoProjects
            ? "Создайте первую карточку товара — превью под Ozon или Wildberries сохранится здесь."
            : "Попробуйте изменить поиск или фильтр маркетплейса."
        }
        action={
          hasNoProjects ? (
            <Link
              href="/editor"
              className={cn(glassButtonVariants({ size: "default" }), "gap-2")}
            >
              <Plus className="size-4" aria-hidden />
              Создать первую карточку
            </Link>
          ) : onResetFilters ? (
            <GlassButton size="default" onClick={onResetFilters}>
              Сбросить фильтры
            </GlassButton>
          ) : null
        }
        className="py-14 sm:py-16"
      />
    </motion.div>
  )
}

export { ProjectsEmptyState }
export type { ProjectsEmptyStateProps }
