"use client"

import {
  Download,
  Loader2,
  Pencil,
  Trash2,
} from "lucide-react"
import Link from "next/link"
import { motion } from "framer-motion"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { GlassCard } from "@/components/ui/glass-card"
import type { Project } from "@/lib/constants/mock-projects"
import { cn } from "@/lib/utils"

type ProjectCardProps = {
  project: Project
  index?: number
  onDownload: (id: string) => void
  onDelete: (id: string) => void
}

const MARKETPLACE_LABEL: Record<Project["marketplace"], string> = {
  ozon: "Ozon",
  wb: "WB",
}

function formatCreatedAt(iso: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso))
}

function ProjectCard({
  project,
  index = 0,
  onDownload,
  onDelete,
}: ProjectCardProps) {
  const isReady = project.status === "ready"

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.32,
        delay: Math.min(index * 0.05, 0.3),
        ease: "easeOut",
      }}
    >
      <GlassCard
        padding="none"
        className="group flex h-full flex-col overflow-hidden border-white/10"
      >
        <div
          className="relative aspect-[3/4] overflow-hidden border-b border-white/8"
          style={{ background: project.previewGradient }}
        >
          <div
            aria-hidden
            className="absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(255,255,255,0.08),transparent_55%)]"
          />
          <div className="absolute inset-x-4 top-4 flex items-start justify-between gap-2">
            <Badge
              variant="secondary"
              className="rounded-md border border-white/10 bg-black/35 text-[10px] uppercase tracking-wider text-copper backdrop-blur-sm"
            >
              {MARKETPLACE_LABEL[project.marketplace]}
            </Badge>
            <Badge
              variant="secondary"
              className={cn(
                "rounded-md border text-[10px] font-medium tracking-wide backdrop-blur-sm",
                isReady
                  ? "border-emerald/30 bg-emerald/15 text-emerald"
                  : "border-amber/30 bg-amber/15 text-amber"
              )}
            >
              {isReady ? (
                "Готово"
              ) : (
                <span className="inline-flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" aria-hidden />
                  В процессе
                </span>
              )}
            </Badge>
          </div>

          <div className="absolute inset-x-6 bottom-6 top-16 flex items-center justify-center">
            <div className="flex h-full w-full max-w-[11rem] flex-col justify-between rounded-xl border border-white/15 bg-white/5 p-3 shadow-[0_12px_40px_rgba(0,0,0,0.35)] backdrop-blur-[2px]">
              <div className="space-y-2">
                <div className="h-2 w-1/3 rounded-full bg-emerald/40" />
                <div className="h-2 w-2/3 rounded-full bg-white/20" />
                <div className="h-2 w-1/2 rounded-full bg-white/12" />
              </div>
              <div className="mt-auto space-y-2">
                <div
                  className="aspect-square w-full rounded-lg border border-white/10 bg-gradient-to-br from-emerald/25 via-transparent to-copper/20"
                  aria-hidden
                />
                <p className="truncate text-center text-[10px] font-medium tracking-wide text-white/70">
                  {project.accentLabel}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 p-4">
          <div className="space-y-1">
            <h3 className="font-heading line-clamp-2 text-base font-semibold leading-snug tracking-tight">
              {project.title}
            </h3>
            <p className="text-xs text-muted-foreground">
              Создан {formatCreatedAt(project.createdAt)}
            </p>
          </div>

          <div className="mt-auto flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isReady}
              onClick={() => onDownload(project.id)}
              className="gap-1.5 border-white/12 bg-white/5"
            >
              <Download className="size-3.5" aria-hidden />
              Скачать ZIP
            </Button>
            <Link
              href={`/editor/${project.id}`}
              className={cn(
                buttonVariants({ size: "sm", variant: "outline" }),
                "gap-1.5 border-white/12 bg-white/5"
              )}
            >
              <Pencil className="size-3.5" aria-hidden />
              Редактировать
            </Link>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={() => onDelete(project.id)}
              className="gap-1.5"
              aria-label={`Удалить проект «${project.title}»`}
            >
              <Trash2 className="size-3.5" aria-hidden />
              Удалить
            </Button>
          </div>
        </div>
      </GlassCard>
    </motion.div>
  )
}

export { ProjectCard }
export type { ProjectCardProps }
