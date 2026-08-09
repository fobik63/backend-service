"use client"

import {
  Coins,
  FolderKanban,
  LogOut,
  Settings,
  UserRound,
} from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"

type ProfileSheetUser = {
  name: string
  email?: string
  avatarUrl?: string | null
  statusLabel?: string
}

type ProfileSheetProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  user?: ProfileSheetUser
  balance?: { current: number; limit: number }
  onLogout?: () => void
  /** Opens tariffs/balance dialog without leaving the current screen. */
  onTopUp?: () => void
}

const DEFAULT_USER: ProfileSheetUser = {
  name: "Гость",
  email: undefined,
  avatarUrl: null,
  statusLabel: "FREE",
}

const QUICK_LINKS = [
  {
    href: "/projects",
    label: "Мои проекты",
    icon: FolderKanban,
  },
  {
    href: "/settings",
    label: "Настройки",
    icon: Settings,
  },
] as const

function ProfileSheet({
  open,
  onOpenChange,
  user = DEFAULT_USER,
  balance = { current: 0, limit: 50 },
  onLogout,
  onTopUp,
}: ProfileSheetProps) {
  const router = useRouter()
  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  const openPricing = () => {
    onOpenChange(false)
    onTopUp?.()
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="gap-0 bg-[#10141a]">
        <SheetHeader>
          <div className="flex items-center gap-3">
            <Avatar size="default">
              {user.avatarUrl ? (
                <AvatarImage src={user.avatarUrl} alt={user.name} />
              ) : null}
              <AvatarFallback className="bg-sage/60 text-emerald">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <SheetTitle className="truncate">{user.name}</SheetTitle>
              {user.email ? (
                <SheetDescription className="truncate">
                  {user.email}
                </SheetDescription>
              ) : (
                <SheetDescription>Личный кабинет</SheetDescription>
              )}
            </div>
          </div>
          {user.statusLabel ? (
            <Badge
              variant="secondary"
              className="mt-2 w-fit rounded-md bg-[#1b3e2b] px-2 text-[10px] font-medium uppercase tracking-wider text-emerald"
            >
              {user.statusLabel}
            </Badge>
          ) : null}
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3.5">
            <div className="mb-2 flex items-center gap-2 text-xs text-text-muted">
              <Coins className="size-3.5 text-amber" aria-hidden />
              <span>Баланс монет</span>
            </div>
            <p className="font-heading text-sm font-semibold text-foreground">
              {balance.current}{" "}
              <span className="font-normal text-text-muted">
                / {balance.limit} монет
              </span>
            </p>
            {onTopUp ? (
              <button
                type="button"
                onClick={openPricing}
                className={cn(
                  buttonVariants({ size: "sm" }),
                  "mt-3 w-full gap-1.5"
                )}
              >
                Пополнить баланс
              </button>
            ) : null}
          </div>

          <nav aria-label="Быстрые действия профиля">
            <ul className="flex flex-col gap-0.5">
              {onTopUp ? (
                <li>
                  <button
                    type="button"
                    onClick={openPricing}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm text-text-muted transition-colors hover:bg-white/[0.04] hover:text-foreground"
                  >
                    <Coins className="size-4 shrink-0 text-copper/80" aria-hidden />
                    Тарифы и баланс
                  </button>
                </li>
              ) : null}
              {QUICK_LINKS.map((item) => {
                const Icon = item.icon
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={() => onOpenChange(false)}
                      className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm text-text-muted transition-colors hover:bg-white/[0.04] hover:text-foreground"
                    >
                      <Icon className="size-4 shrink-0 text-copper/80" aria-hidden />
                      <span>{item.label}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </nav>

          <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-3 py-3">
            <div className="flex items-start gap-2.5 text-sm text-text-muted">
              <UserRound className="mt-0.5 size-4 shrink-0 text-emerald" aria-hidden />
              <p>
                Полные данные аккаунта и интеграции — в разделе{" "}
                <Link
                  href="/settings"
                  onClick={() => onOpenChange(false)}
                  className="text-emerald underline-offset-2 hover:underline"
                >
                  Настройки
                </Link>
                .
              </p>
            </div>
          </div>
        </div>

        <SheetFooter>
          <button
            type="button"
            onClick={() => {
              onOpenChange(false)
              if (onLogout) {
                onLogout()
                return
              }
              router.push("/login")
            }}
            className={cn(
              buttonVariants({ variant: "outline" }),
              "w-full gap-2 border-white/10 bg-transparent text-destructive hover:bg-destructive/10 hover:text-destructive"
            )}
          >
            <LogOut className="size-4" aria-hidden />
            Выйти
          </button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

export { ProfileSheet }
export type { ProfileSheetProps, ProfileSheetUser }
