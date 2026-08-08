import type { ElementType, HTMLAttributes, ReactNode } from "react"

import { cn } from "@/lib/utils"

type SectionHeaderProps = Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  title: ReactNode
  subtitle?: ReactNode
  align?: "left" | "center"
  as?: Extract<ElementType, "h1" | "h2" | "h3" | "h4">
}

function SectionHeader({
  title,
  subtitle,
  align = "left",
  as: Tag = "h2",
  className,
  ...props
}: SectionHeaderProps) {
  return (
    <div
      data-slot="section-header"
      className={cn(
        "flex flex-col gap-3",
        align === "center" && "items-center text-center",
        className
      )}
      {...props}
    >
      <div
        className={cn(
          "flex flex-col gap-2.5",
          align === "center" && "items-center"
        )}
      >
        <Tag className="font-heading text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          {title}
        </Tag>
        <span
          aria-hidden
          className={cn(
            "h-0.5 w-16 rounded-full",
            "bg-gradient-to-r from-emerald via-emerald-deep to-transparent"
          )}
        />
      </div>
      {subtitle ? (
        <p
          className={cn(
            "max-w-2xl text-sm leading-relaxed text-text-muted md:text-base",
            align === "center" && "mx-auto"
          )}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  )
}

export { SectionHeader }
export type { SectionHeaderProps }
