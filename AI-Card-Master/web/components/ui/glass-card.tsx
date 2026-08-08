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
        "rounded-xl border border-white/5 copper-border",
        "bg-[#14171d]/60 backdrop-blur-xl",
        "shadow-[0_8px_30px_rgba(0,0,0,0.25)]",
        "transition-[transform,box-shadow] duration-300 ease-out",
        hoverLift &&
          "hover:-translate-y-1.5 hover:shadow-[0_16px_40px_rgba(0,0,0,0.35)]",
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
