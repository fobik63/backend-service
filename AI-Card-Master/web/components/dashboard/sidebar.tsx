"use client"

import { Coins, Plus } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { DASHBOARD_NAV } from "@/lib/constants/dashboard-nav"
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
}

const DEFAULT_USER: SidebarUser = {
  name: "Алексей Иванов",
  avatarUrl: null,
  statusLabel: "PRO",
}

const DEFAULT_BALANCE: SidebarBalance = {
  current: 48,
  limit: 50,
}

function isNavActive(pathname: string, href: string) {
  if (href === "/projects") {
    return pathname === "/projects" || pathname === "/projects/"
  }
  return pathname === href || pathname.startsWith(`${href}/`)
}

function Sidebar({
  user = DEFAULT_USER,
  balance = DEFAULT_BALANCE,
  className,
  onNavigate,
}: SidebarProps) {
  const pathname = usePathname()
  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <aside
      className={cn(
        "flex h-full w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
        className
      )}
      aria-label="Навигация личного кабинета"
    >
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <BrandLogo />
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="flex flex-col gap-0.5">
          {DASHBOARD_NAV.map((item) => {
            const Icon = item.icon
            const active = isNavActive(pathname, item.href)

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
                  <span className="truncate">{item.label}</span>
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
            <span>Баланс монет</span>
          </div>
          <p className="mb-3 font-heading text-sm font-semibold tracking-tight text-sidebar-foreground">
            {balance.current}{" "}
            <span className="font-normal text-text-muted">
              / {balance.limit} монет
            </span>
          </p>
          <div
            className="mb-3 h-1.5 overflow-hidden rounded-full bg-white/8"
            role="progressbar"
            aria-valuenow={balance.current}
            aria-valuemin={0}
            aria-valuemax={balance.limit}
            aria-label="Использовано монет"
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald to-emerald-deep"
              style={{
                width: `${Math.min(
                  100,
                  (balance.current / Math.max(balance.limit, 1)) * 100
                )}%`,
              }}
            />
          </div>
          <Link
            href="/dashboard/billing"
            onClick={onNavigate}
            className={cn(buttonVariants({ size: "sm" }), "w-full gap-1.5")}
          >
            <Plus className="size-3.5" aria-hidden />
            Пополнить
          </Link>
        </div>

        <div className="flex items-center gap-3 rounded-lg px-1 py-1">
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
        </div>
      </div>
    </aside>
  )
}

export { Sidebar }
export type { SidebarProps, SidebarUser, SidebarBalance }
