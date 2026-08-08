"use client"

import { Check } from "lucide-react"
import { motion } from "framer-motion"

import { cn } from "@/lib/utils"

type CategoryChipProps = {
  label: string
  selected: boolean
  onToggle: () => void
  disabled?: boolean
}

function CategoryChip({
  label,
  selected,
  onToggle,
  disabled = false,
}: CategoryChipProps) {
  return (
    <motion.button
      type="button"
      role="checkbox"
      aria-checked={selected}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      whileHover={disabled ? undefined : { y: -1 }}
      whileTap={disabled ? undefined : { scale: 0.97 }}
      transition={{ type: "spring", stiffness: 420, damping: 28 }}
      className={cn(
        "inline-flex w-full items-center gap-2 rounded-xl border px-4 py-2.5 text-left",
        "font-heading text-sm font-medium sm:px-5 sm:py-3 sm:text-base",
        "bg-[rgba(22,24,30,0.75)] backdrop-blur-md",
        "outline-none transition-[border-color,box-shadow,background-color,color] duration-200",
        "focus-visible:ring-2 focus-visible:ring-emerald/50 focus-visible:ring-offset-2 focus-visible:ring-offset-loft",
        "disabled:pointer-events-none disabled:opacity-50",
        selected
          ? "border-emerald/60 bg-emerald/10 text-foreground shadow-[0_0_0_1px_rgba(16,185,129,0.2)]"
          : "border-white/10 text-text-muted hover:border-white/20 hover:text-foreground"
      )}
    >
      <span
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors",
          selected
            ? "border-emerald bg-emerald text-primary-foreground"
            : "border-white/20 bg-white/5 text-transparent"
        )}
        aria-hidden
      >
        <Check className="size-3 stroke-[2.5]" />
      </span>
      {label}
    </motion.button>
  )
}

export { CategoryChip }
export type { CategoryChipProps }
