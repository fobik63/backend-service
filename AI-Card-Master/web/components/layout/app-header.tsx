"use client"

import {
  ChevronDown,
  FolderKanban,
  Home,
  Languages,
  LogOut,
} from "lucide-react"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useRef, useState, type ReactNode } from "react"

import { BrandLogo } from "@/components/dashboard/brand-logo"
import { Breadcrumbs } from "@/components/dashboard/breadcrumbs"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useI18n, type Locale } from "@/lib/i18n"
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

function isEditorPath(pathname: string) {
  return pathname.startsWith("/editor")
}

function isProjectsPath(pathname: string) {
  return pathname === "/projects" || pathname.startsWith("/projects/")
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
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const initials = (user.name || "Г")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "Г"

  /** Leaving the editor via Soft Router freezes on Fabric teardown — use a hard load. */
  const go = (href: string) => {
    if (pathname === href) return
    if (isEditorPath(pathname) && !href.startsWith("/editor")) {
      window.location.assign(href)
      return
    }
    router.push(href)
  }

  const handleLogout = () => {
    setIsMenuOpen(false)
    if (onLogout) {
      onLogout()
      return
    }
    if (isEditorPath(pathname)) {
      window.location.assign("/login")
      return
    }
    router.push("/login")
  }

  useEffect(() => {
    if (!isMenuOpen) return

    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (menuRef.current && !menuRef.current.contains(target)) {
        setIsMenuOpen(false)
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsMenuOpen(false)
    }

    document.addEventListener("mousedown", onPointerDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onPointerDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [isMenuOpen])

  return (
    <header
      className={cn(
        "sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-zinc-800/80 bg-zinc-900/80 px-4 backdrop-blur-xl sm:px-6",
        className
      )}
      aria-label={t("nav.ariaHeader")}
    >
      <BrandLogo
        href="/"
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
          go("/")
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

        <div ref={menuRef} className="relative">
          {isMenuOpen ? (
            <button
              type="button"
              className="fixed inset-0 z-40 cursor-default bg-transparent"
              aria-label={t("common.closeMenu")}
              onClick={() => setIsMenuOpen(false)}
            />
          ) : null}

          <button
            type="button"
            className={cn(
              "relative z-50 inline-flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm transition-colors",
              "hover:bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              isMenuOpen && "bg-muted"
            )}
            aria-label={t("topBar.profileMenu")}
            aria-expanded={isMenuOpen}
            aria-haspopup="menu"
            onClick={() => setIsMenuOpen((open) => !open)}
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
              className={cn(
                "size-3.5 text-text-muted transition-transform",
                isMenuOpen && "rotate-180"
              )}
              aria-hidden
            />
          </button>

          {isMenuOpen ? (
            <div
              role="menu"
              className="absolute right-0 top-full z-50 mt-2 min-w-48 rounded-lg border border-zinc-800 bg-zinc-900 p-1 shadow-lg"
            >
              {isProjectsPath(pathname) ? (
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground outline-none hover:bg-muted focus-visible:bg-muted"
                  onClick={() => {
                    setIsMenuOpen(false)
                    go("/")
                  }}
                >
                  <Home className="size-4" aria-hidden />
                  {t("nav.home")}
                </button>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground outline-none hover:bg-muted focus-visible:bg-muted"
                  onClick={() => {
                    setIsMenuOpen(false)
                    go("/projects")
                  }}
                >
                  <FolderKanban className="size-4" aria-hidden />
                  {t("nav.projects")}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-destructive outline-none hover:bg-destructive/10 focus-visible:bg-destructive/10"
                onClick={handleLogout}
              >
                <LogOut className="size-4" aria-hidden />
                {t("common.logout")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  )
}

export { AppHeader }
export type { AppHeaderProps, AppHeaderUser }
