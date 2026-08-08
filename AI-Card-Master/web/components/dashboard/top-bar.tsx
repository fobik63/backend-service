"use client"

import {
  Bell,
  ChevronDown,
  Languages,
  LogOut,
  Menu,
  Settings,
  UserRound,
} from "lucide-react"
import Link from "next/link"

import { Breadcrumbs } from "@/components/dashboard/breadcrumbs"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useI18n, type Locale } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type TopBarUser = {
  name: string
  email?: string
  avatarUrl?: string | null
}

type TopBarProps = {
  user?: TopBarUser
  onMenuClick?: () => void
  onOpenProfile?: () => void
  className?: string
}

const DEFAULT_USER: TopBarUser = {
  name: "Алексей Иванов",
  email: "alexey@example.com",
  avatarUrl: null,
}

function TopBar({
  user = DEFAULT_USER,
  onMenuClick,
  onOpenProfile,
  className,
}: TopBarProps) {
  const { locale, setLocale, t } = useI18n()
  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center gap-3 border-b border-border bg-loft-surface/80 px-4 backdrop-blur-md sm:px-6",
        className
      )}
    >
      {onMenuClick ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="lg:hidden"
          aria-label={t("common.openMenu")}
          onClick={onMenuClick}
        >
          <Menu className="size-5" />
        </Button>
      ) : null}

      <Breadcrumbs className="min-w-0 flex-1" />

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-sm text-text-muted transition-colors",
              "hover:bg-muted hover:text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            )}
            aria-label={t("topBar.languageSwitch")}
          >
            <Languages className="size-4" aria-hidden />
            <span className="hidden uppercase sm:inline">{locale}</span>
            <ChevronDown className="size-3.5 opacity-60" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-36">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("common.language")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuRadioGroup
                value={locale}
                onValueChange={(value) => setLocale(value as Locale)}
              >
                <DropdownMenuRadioItem value="ru">
                  {t("topBar.russian")}
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="en">
                  {t("topBar.english")}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              "relative inline-flex size-8 items-center justify-center rounded-lg text-text-muted transition-colors",
              "hover:bg-muted hover:text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            )}
            aria-label={t("common.notifications")}
          >
            <Bell className="size-4" aria-hidden />
            <span
              className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-emerald"
              aria-hidden
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("common.notifications")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <div className="px-2 py-6 text-center text-sm text-text-muted">
                {t("common.noNotifications")}
              </div>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm transition-colors",
              "hover:bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            )}
            aria-label={t("topBar.profileMenu")}
          >
            <Avatar size="sm">
              {user.avatarUrl ? (
                <AvatarImage src={user.avatarUrl} alt={user.name} />
              ) : null}
              <AvatarFallback className="bg-sage/60 text-[10px] text-emerald">
                {initials}
              </AvatarFallback>
            </Avatar>
            <span className="hidden max-w-32 truncate text-foreground md:inline">
              {user.name}
            </span>
            <ChevronDown className="hidden size-3.5 text-text-muted md:inline" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-52">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col gap-0.5">
                  <span className="text-sm font-medium text-foreground">
                    {user.name}
                  </span>
                  {user.email ? (
                    <span className="text-xs text-text-muted">{user.email}</span>
                  ) : null}
                </div>
              </DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem
                className="cursor-pointer gap-2"
                onClick={() => onOpenProfile?.()}
              >
                <UserRound className="size-4" aria-hidden />
                {t("common.profile")}
              </DropdownMenuItem>
              <DropdownMenuItem
                render={<Link href="/settings" />}
                className="cursor-pointer gap-2"
              >
                <Settings className="size-4" aria-hidden />
                {t("common.settings")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem
                variant="destructive"
                className="cursor-pointer gap-2"
                render={<Link href="/login" />}
              >
                <LogOut className="size-4" aria-hidden />
                {t("common.logout")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}

export { TopBar }
export type { TopBarProps, TopBarUser }
