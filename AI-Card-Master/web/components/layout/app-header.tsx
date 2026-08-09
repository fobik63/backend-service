"use client"

import {
  ChevronDown,
  Coins,
  FolderKanban,
  ImagePlus,
  Languages,
  LogOut,
  Settings,
} from "lucide-react"
import { usePathname, useRouter } from "next/navigation"
import { useState, type ReactNode } from "react"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { Breadcrumbs } from "@/components/dashboard/breadcrumbs"
import { TopUpDialog } from "@/components/dashboard/top-up-dialog"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
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
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type AppHeaderUser = {
  name: string
  email?: string
  avatarUrl?: string | null
}

type AppHeaderProps = {
  user?: AppHeaderUser
  onLogout?: () => void
  /** Extra actions on the right (e.g. editor save) before the profile menu. */
  trailing?: ReactNode
  /** Hide breadcrumbs (useful in editor). */
  showBreadcrumbs?: boolean
  className?: string
}

const DEFAULT_USER: AppHeaderUser = {
  name: "Гость",
  email: undefined,
  avatarUrl: null,
}

function resetEditorIfNeeded() {
  if (typeof window === "undefined") return
  if (!window.location.pathname.startsWith("/editor")) return
  const store = useEditorStore.getState()
  store.setBusyKind("idle")
  store.setBusyProgress(null)
  store.reset()
}

function AppHeader({
  user = DEFAULT_USER,
  onLogout,
  trailing,
  showBreadcrumbs = true,
  className,
}: AppHeaderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { locale, setLocale, t } = useI18n()
  const [pricingOpen, setPricingOpen] = useState(false)
  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  const go = (href: string) => {
    if (pathname === href || (href === "/projects" && pathname === "/projects/")) {
      return
    }
    resetEditorIfNeeded()
    router.push(href)
  }

  return (
    <>
      <header
        className={cn(
          "sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-zinc-800/80 bg-zinc-900/80 px-4 backdrop-blur-xl sm:px-6",
          className
        )}
        aria-label={t("nav.ariaHeader")}
      >
      <BrandLogo
        href="/projects"
        onClick={(event) => {
          if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          ) {
            return
          }
          event.preventDefault()
          go("/projects")
        }}
      />

      {showBreadcrumbs ? (
        <Breadcrumbs className="min-w-0 flex-1" />
      ) : (
        <div className="min-w-0 flex-1" />
      )}

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        {trailing}

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
            <ChevronDown
              className="size-3.5 text-text-muted"
              aria-hidden
            />
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
                onClick={() => go("/editor/new")}
              >
                <ImagePlus className="size-4" aria-hidden />
                {t("nav.createProject")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="cursor-pointer gap-2"
                onClick={() => go("/projects")}
              >
                <FolderKanban className="size-4" aria-hidden />
                {t("nav.projects")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="cursor-pointer gap-2"
                onClick={() => go("/settings")}
              >
                <Settings className="size-4" aria-hidden />
                {t("common.settings")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="cursor-pointer gap-2"
                onClick={() => setPricingOpen(true)}
              >
                <Coins className="size-4" aria-hidden />
                {t("nav.pricing")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem
                variant="destructive"
                className="cursor-pointer gap-2"
                onClick={() => {
                  resetEditorIfNeeded()
                  if (onLogout) {
                    onLogout()
                    return
                  }
                  router.push("/login")
                }}
              >
                <LogOut className="size-4" aria-hidden />
                {t("common.logout")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      </header>
      <TopUpDialog open={pricingOpen} onOpenChange={setPricingOpen} />
    </>
  )
}

export { AppHeader }
export type { AppHeaderProps, AppHeaderUser }
