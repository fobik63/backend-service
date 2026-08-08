"use client"

import { Check } from "lucide-react"
import type { ReactNode } from "react"
import { motion } from "framer-motion"

import { cn } from "@/lib/utils"

type MarketplaceOptionCardProps = {
  title: string
  description?: string
  selected: boolean
  onSelect: () => void
  logos: ReactNode
  /** Optional secondary label under logos (e.g. combined card title) */
  logoCaption?: string
}

function MarketplaceOptionCard({
  title,
  description,
  selected,
  onSelect,
  logos,
  logoCaption,
}: MarketplaceOptionCardProps) {
  return (
    <motion.button
      type="button"
      role="checkbox"
      aria-checked={selected}
      aria-label={title}
      onClick={onSelect}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: "spring", stiffness: 420, damping: 28 }}
      className={cn(
        "group relative flex w-full flex-col items-stretch gap-4 rounded-2xl border p-5 text-left sm:p-6",
        "bg-[rgba(22,24,30,0.75)] backdrop-blur-md",
        "shadow-[0_8px_30px_rgba(0,0,0,0.25)]",
        "outline-none transition-[border-color,box-shadow,background-color] duration-200",
        "focus-visible:ring-2 focus-visible:ring-emerald/50 focus-visible:ring-offset-2 focus-visible:ring-offset-loft",
        selected
          ? "border-emerald/60 bg-emerald/5 shadow-[0_0_0_1px_rgba(16,185,129,0.25),0_12px_36px_rgba(0,0,0,0.35)]"
          : "border-white/10 hover:border-white/20"
      )}
    >
      <span
        className={cn(
          "absolute right-4 top-4 flex size-6 items-center justify-center rounded-md border transition-colors sm:right-5 sm:top-5",
          selected
            ? "border-emerald bg-emerald text-primary-foreground"
            : "border-white/20 bg-white/5 text-transparent group-hover:border-white/35"
        )}
        aria-hidden
      >
        <Check className="size-3.5 stroke-[2.5]" />
      </span>

      <div className="flex min-h-[3.25rem] items-center gap-3 pr-10">
        {logos}
      </div>

      {logoCaption ? (
        <p className="font-heading text-base font-semibold text-foreground sm:text-lg">
          {logoCaption}
        </p>
      ) : null}

      {description ? (
        <p className="text-sm leading-relaxed text-text-muted">{description}</p>
      ) : null}
    </motion.button>
  )
}

export { MarketplaceOptionCard }
export type { MarketplaceOptionCardProps }
