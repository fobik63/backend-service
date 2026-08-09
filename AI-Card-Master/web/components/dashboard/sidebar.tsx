"use client"

import { Coins, Plus } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { DASHBOARD_NAV } from "@/lib/constants/dashboard-nav"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type SidebarUser = {
  name: string
  avatarUrl?: string | null
  statusLabel: string
}

type SidebarBalance = {
  current: number
  limit: number
}

type SidebarProps = {
  user?: SidebarUser
  balance?: SidebarBalance
  className?: string
  onNavigate?: () => void
  onOpenProfile?: () => void
  onTopUp?: () => void
}

const DEFAULT_USER: SidebarUser = {
  name: "Гость",
  avatarUrl: null,
  statusLabel: "FREE",
}

const DEFAULT_BALANCE: SidebarBalance = {
  current: 0,
  limit: 50,
}

function isNavActive(pathname: string, href: string) {
  if (href === "/projects") {
    return pathname === "/projects" || pathname === "/projects/"
  }
  if (href === "/editor") {
    return pathname === "/editor" || pathname.startsWith("/editor/")
  }
  return pathname === href || pathname.startsWith(`${href}/`)
}

function Sidebar({
  user = DEFAULT_USER,
  balance = DEFAULT_BALANCE,
  className,
  onNavigate,
  onOpenProfile,
  onTopUp,
}: SidebarProps) {
  const pathname = usePathname()
  const { t } = useI18n()
  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <aside
      className={cn(
        "flex h-full w-64 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-900/60 text-sidebar-foreground backdrop-blur-xl",
        className
      )}
      aria-label={t("nav.ariaSidebar")}
    >
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <BrandLogo />
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="flex flex-col gap-0.5">
          {DASHBOARD_NAV.map((item) => {
            const Icon = item.icon
            const active = isNavActive(pathname, item.href)
            const label = t(`nav.${item.id}`)

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-text-muted hover:bg-white/[0.04] hover:text-sidebar-foreground"
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-emerald" : "text-copper/70"
                    )}
                    aria-hidden
                  />
                  <span className="truncate">{label}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="mt-auto space-y-3 border-t border-sidebar-border p-3">
        <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-center gap-2 text-xs text-text-muted">
            <Coins className="size-3.5 text-amber" aria-hidden />
            <span>{t("nav.coins")}</span>
          </div>
          <p className="mb-3 font-heading text-sm font-semibold tracking-tight text-sidebar-foreground">
            {balance.current}{" "}
            <span className="font-normal text-text-muted">
              / {balance.limit}
            </span>
          </p>
          <div
            className="mb-3 h-1.5 overflow-hidden rounded-full bg-white/8"
            role="progressbar"
            aria-valuenow={balance.current}
            aria-valuemin={0}
            aria-valuemax={balance.limit}
            aria-label={t("nav.coins")}
          >
            <div
              className="h-full rounded-full bg-foreground"
              style={{
                width: `${Math.min(
                  100,
                  (balance.current / Math.max(balance.limit, 1)) * 100
                )}%`,
              }}
            />
          </div>
          {onTopUp ? (
            <button
              type="button"
              onClick={() => {
                onTopUp()
                onNavigate?.()
              }}
              className={cn(buttonVariants({ size: "sm" }), "w-full gap-1.5")}
            >
              <Plus className="size-3.5" aria-hidden />
              {t("nav.topUp")}
            </button>
          ) : (
            <button
              type="button"
              disabled
              className={cn(buttonVariants({ size: "sm" }), "w-full gap-1.5")}
            >
              <Plus className="size-3.5" aria-hidden />
              {t("nav.topUp")}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => {
            onOpenProfile?.()
            onNavigate?.()
          }}
          className="flex w-full items-center gap-3 rounded-lg px-1 py-1 text-left transition-colors hover:bg-white/[0.04] outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label={t("common.profile")}
        >
          <Avatar size="default">
            {user.avatarUrl ? (
              <AvatarImage src={user.avatarUrl} alt={user.name} />
            ) : null}
            <AvatarFallback className="bg-sage/60 text-emerald">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-sidebar-foreground">
              {user.name}
            </p>
            <Badge
              variant="secondary"
              className="mt-1 h-5 rounded-md bg-[#1b3e2b] px-2 text-[10px] font-medium uppercase tracking-wider text-emerald"
            >
              {user.statusLabel}
            </Badge>
          </div>
        </button>
      </div>
    </aside>
  )
}

export { Sidebar }
export type { SidebarProps, SidebarUser, SidebarBalance }
