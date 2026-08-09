import type { HTMLAttributes, ReactNode } from "react"

import { cn } from "@/lib/utils"

type GlassCardProps = HTMLAttributes<HTMLDivElement> & {
  children?: ReactNode
  /** Soft lift on hover. Default: true */
  hoverLift?: boolean
  padding?: "none" | "sm" | "md" | "lg"
}

const paddingMap = {
  none: "",
  sm: "p-4",
  md: "p-6",
  lg: "p-8",
} as const

function GlassCard({
  className,
  children,
  hoverLift = true,
  padding = "md",
  ...props
}: GlassCardProps) {
  return (
    <div
      data-slot="glass-card"
      className={cn(
        "rounded-xl border border-zinc-800/80 bg-zinc-900/60 backdrop-blur-xl",
        "shadow-panel",
        "transition-[transform,border-color,box-shadow] duration-200 ease-out",
        hoverLift &&
          "hover:-translate-y-0.5 hover:border-zinc-700/80 hover:shadow-[0_16px_40px_rgba(0,0,0,0.35)]",
        paddingMap[padding],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export { GlassCard }
export type { GlassCardProps }
