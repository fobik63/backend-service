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
import { tryEditorDocumentToState } from "@/lib/editor/editor-document"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type ProjectCardProps = {
  project: Project
  index?: number
  onDelete: (id: string) => Promise<void>
  deleting?: boolean
}

const MARKETPLACE_LABEL: Record<
  NonNullable<Project["marketplace"]>,
  string
> = {
  ozon: "Ozon",
  wb: "WB",
}

function formatRub(value: number): string {
  return `${value.toLocaleString("ru-RU")} ₽`
}

function ProjectCard({
  project,
  index = 0,
  onDelete,
  deleting = false,
}: ProjectCardProps) {
  const { t, locale } = useI18n()
  const isReady = project.status === "ready"
  const editorState = project.editorDocument
    ? tryEditorDocumentToState(project.editorDocument)
    : null

  // Prefer cutout so baked-in card text from marketing composites cannot overlap.
  const thumbSrc = project.productImage ?? project.previewImage

  const createdAt = new Date(project.createdAt)
  const createdLabel = Number.isNaN(createdAt.getTime())
    ? "—"
    : new Intl.DateTimeFormat(locale === "en" ? "en-US" : "ru-RU", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(createdAt)

  const hasPrice =
    typeof project.priceRub === "number" && project.priceRub >= 0

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
        <div className="relative aspect-[3/4] overflow-hidden border-b border-white/8 bg-loft-surface">
          {thumbSrc ? (
            <Image
              src={thumbSrc}
              alt={`${project.title}`}
              fill
              priority={index === 0}
              sizes="(max-width: 768px) 50vw, (max-width: 1200px) 33vw, 280px"
              className="object-cover object-center transition-transform duration-500 group-hover:scale-[1.03]"
            />
          ) : (
            <div
              aria-hidden
              className="absolute inset-0 bg-gradient-to-br from-zinc-800/80 via-zinc-900 to-zinc-950"
            />
          )}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/35 via-transparent to-black/25"
          />

          <div className="absolute inset-x-3 top-3 z-10 flex items-start justify-between gap-2">
            {project.marketplace ? (
              <Badge
                variant="secondary"
                className="rounded-md border border-white/10 bg-black/45 text-[10px] uppercase tracking-wider text-copper backdrop-blur-sm"
              >
                {MARKETPLACE_LABEL[project.marketplace]}
              </Badge>
            ) : (
              <span />
            )}
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
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-4 p-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="flex min-w-0 items-start justify-between gap-3">
              <h3 className="font-heading min-w-0 flex-1 truncate text-base font-semibold leading-snug tracking-tight">
                {project.title}
              </h3>
              {hasPrice ? (
                <div className="flex shrink-0 items-baseline gap-1.5 pt-0.5">
                  <span className="text-sm font-semibold leading-none tracking-tight text-foreground">
                    {formatRub(project.priceRub!)}
                  </span>
                  {typeof project.oldPriceRub === "number" &&
                  project.oldPriceRub > 0 ? (
                    <span className="text-[10px] font-normal leading-none text-muted-foreground line-through">
                      {formatRub(project.oldPriceRub)}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            {project.accentLabel ? (
              <span className="inline-flex w-fit max-w-full truncate rounded-md border border-white/12 bg-white/5 px-2 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground">
                {project.accentLabel}
              </span>
            ) : null}
            {project.subtitle ? (
              <p className="line-clamp-1 text-xs text-muted-foreground">
                {project.subtitle}
              </p>
            ) : null}
            <p className="truncate text-xs text-muted-foreground">
              {t("projects.created")} {createdLabel}
            </p>
          </div>

          <div className="mt-auto flex min-w-0 flex-wrap gap-2">
            <ExportButton
              variant="compact"
              disabled={!isReady}
              projectTitle={project.title}
              productImageUrl={
                editorState?.productPreviewUrl ??
                project.productImage ??
                project.previewImage ??
                undefined
              }
              pages={editorState?.pages}
              softbox={editorState?.softbox}
            />
            <Link
              href={`/editor/${project.id}`}
              className={cn(
                buttonVariants({ size: "sm", variant: "outline" }),
                "min-w-0 gap-1.5 border-white/12 bg-white/5"
              )}
            >
              <Pencil className="size-3.5 shrink-0" aria-hidden />
              <span className="truncate">{t("common.edit")}</span>
            </Link>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={deleting}
              onClick={() => void onDelete(project.id)}
              className="min-w-0 gap-1.5"
              aria-label={`${t("common.delete")} «${project.title}»`}
            >
              {deleting ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="size-3.5" aria-hidden />
              )}
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
