"use client"

import { ChevronRight } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { DASHBOARD_BREADCRUMB_LABELS } from "@/lib/constants/dashboard-nav"
import { cn } from "@/lib/utils"

type BreadcrumbsProps = {
  className?: string
}

function Breadcrumbs({ className }: BreadcrumbsProps) {
  const pathname = usePathname()
  const segments = pathname.split("/").filter(Boolean)

  const crumbs = segments.map((segment, index) => {
    const href = `/${segments.slice(0, index + 1).join("/")}`
    const label =
      DASHBOARD_BREADCRUMB_LABELS[segment] ??
      decodeURIComponent(segment).replace(/-/g, " ")
    const isLast = index === segments.length - 1

    return { href, label, isLast }
  })

  if (crumbs.length === 0) {
    return null
  }

  return (
    <nav aria-label="Хлебные крошки" className={cn("min-w-0", className)}>
      <ol className="flex flex-wrap items-center gap-1 text-sm">
        {crumbs.map((crumb) => (
          <li key={crumb.href} className="flex items-center gap-1">
            {crumb.isLast ? (
              <span
                className="truncate font-medium text-foreground"
                aria-current="page"
              >
                {crumb.label}
              </span>
            ) : (
              <>
                <Link
                  href={crumb.href}
                  className="truncate text-text-muted transition-colors hover:text-foreground"
                >
                  {crumb.label}
                </Link>
                <ChevronRight
                  className="size-3.5 shrink-0 text-text-muted/60"
                  aria-hidden
                />
              </>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export { Breadcrumbs }
