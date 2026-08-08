import { Leaf, Sparkles, type LucideIcon } from "lucide-react"
import type { HTMLAttributes, ReactNode } from "react"

import { cn } from "@/lib/utils"

const iconMap = {
  leaf: Leaf,
  sparkles: Sparkles,
} as const

type BotanicalBadgeIcon = keyof typeof iconMap

type BotanicalBadgeProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode
  /** Built-in leaf or sparkles icon. Ignored when `icon` is a Lucide component. */
  variant?: BotanicalBadgeIcon
  /** Custom Lucide icon override */
  icon?: LucideIcon
}

function BotanicalBadge({
  children,
  className,
  variant = "leaf",
  icon,
  ...props
}: BotanicalBadgeProps) {
  const Icon = icon ?? iconMap[variant]

  return (
    <span
      data-slot="botanical-badge"
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1.5",
        "rounded-md bg-[#1b3e2b] px-2.5 py-1",
        "text-xs font-medium tracking-wide text-emerald whitespace-nowrap",
        "[&_svg]:pointer-events-none [&_svg]:size-3 [&_svg]:shrink-0",
        className
      )}
      {...props}
    >
      <Icon aria-hidden />
      {children}
    </span>
  )
}

export { BotanicalBadge }
export type { BotanicalBadgeProps, BotanicalBadgeIcon }
