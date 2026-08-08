"use client"

import { Loader2, Pencil, Trash2 } from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { motion } from "framer-motion"

import { ExportButton } from "@/components/editor/export-button"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { GlassCard } from "@/components/ui/glass-card"
import type { Project } from "@/lib/constants/mock-projects"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type ProjectCardProps = {
  project: Project
  index?: number
  onDelete: (id: string) => void
}

const MARKETPLACE_LABEL: Record<Project["marketplace"], string> = {
  ozon: "Ozon",
  wb: "WB",
}

function ProjectCard({ project, index = 0, onDelete }: ProjectCardProps) {
  const { t, locale } = useI18n()
  const isReady = project.status === "ready"

  const createdLabel = new Intl.DateTimeFormat(
    locale === "en" ? "en-US" : "ru-RU",
    {
      day: "numeric",
      month: "short",
      year: "numeric",
    }
  ).format(new Date(project.createdAt))

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
        <div className="relative aspect-[3/4] overflow-hidden border-b border-white/8 bg-[#14161c]">
          <Image
            src={project.previewImage}
            alt={`${project.title}`}
            fill
            sizes="(max-width: 768px) 50vw, (max-width: 1200px) 33vw, 280px"
            className="object-cover object-center transition-transform duration-500 group-hover:scale-[1.03]"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-black/25"
          />
          <div className="absolute inset-x-4 top-4 flex items-start justify-between gap-2">
            <Badge
              variant="secondary"
              className="rounded-md border border-white/10 bg-black/45 text-[10px] uppercase tracking-wider text-copper backdrop-blur-sm"
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
                t("common.ready")
              ) : (
                <span className="inline-flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" aria-hidden />
                  {t("common.processing")}
                </span>
              )}
            </Badge>
          </div>
          <div className="absolute inset-x-4 bottom-4">
            <span className="inline-flex rounded-md border border-white/12 bg-black/40 px-2 py-1 text-[10px] font-medium tracking-wide text-white/85 backdrop-blur-sm">
              {project.accentLabel}
            </span>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 p-4">
          <div className="space-y-1">
            <h3 className="font-heading line-clamp-2 text-base font-semibold leading-snug tracking-tight">
              {project.title}
            </h3>
            <p className="text-xs text-muted-foreground">
              {t("projects.created")} {createdLabel}
            </p>
          </div>

          <div className="mt-auto flex flex-wrap gap-2">
            <ExportButton
              variant="compact"
              disabled={!isReady}
              projectTitle={project.title}
              productImageUrl={project.previewImage}
            />
            <Link
              href={`/editor/${project.id}`}
              className={cn(
                buttonVariants({ size: "sm", variant: "outline" }),
                "gap-1.5 border-white/12 bg-white/5"
              )}
            >
              <Pencil className="size-3.5" aria-hidden />
              {t("common.edit")}
            </Link>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={() => onDelete(project.id)}
              className="gap-1.5"
              aria-label={`${t("common.delete")} «${project.title}»`}
            >
              <Trash2 className="size-3.5" aria-hidden />
              {t("common.delete")}
            </Button>
          </div>
        </div>
      </GlassCard>
    </motion.div>
  )
}

export { ProjectCard }
export type { ProjectCardProps }
