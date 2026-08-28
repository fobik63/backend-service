"use client"

import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { AppHeader } from "@/components/layout/app-header"
import {
  BuyCoinsProvider,
  useBuyCoins,
} from "@/components/layout/buy-coins-provider"
import { fetchCurrentUser } from "@/lib/api/auth"
import {
  displayNameFromEmail,
  persistUser,
} from "@/lib/auth/session"
import { IS_MOCK, MOCK_AUTH_USER } from "@/lib/constants/mock"
import { useAuthStore } from "@/lib/store"
import { cn } from "@/lib/utils"

type AppShellProps = {
  children: ReactNode
  /** `workspace` — padded main; `editor` — flush full-height content under header. */
  variant?: "workspace" | "editor"
}

function AppShell({ children, variant = "workspace" }: AppShellProps) {
  return (
    <BuyCoinsProvider>
      <AppShellFrame variant={variant}>{children}</AppShellFrame>
    </BuyCoinsProvider>
  )
}

function AppShellFrame({ children, variant = "workspace" }: AppShellProps) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const hydrated = useAuthStore((s) => s.hydrated)
  const hydrateFromStorage = useAuthStore((s) => s.hydrateFromStorage)
  const setUser = useAuthStore((s) => s.setUser)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  useEffect(() => {
    hydrateFromStorage()
  }, [hydrateFromStorage])

  useEffect(() => {
    if (!hydrated) return

    if (IS_MOCK) {
      setUser(MOCK_AUTH_USER)
      return
    }

    if (!accessToken) {
      router.replace("/login")
      return
    }

    let cancelled = false
    void (async () => {
      try {
        const profile = await fetchCurrentUser()
        if (cancelled) return
        setUser(profile)
        persistUser(profile)
      } catch {
        if (cancelled) return
        clearAuth()
        router.replace("/login")
      }
    })()

    return () => {
      cancelled = true
    }
  }, [hydrated, accessToken, setUser, clearAuth, router])

  const handleLogout = () => {
    clearAuth()
    if (IS_MOCK) {
      // Hard load when leaving editor — Soft Router can hang on Fabric teardown.
      if (typeof window !== "undefined" && window.location.pathname.startsWith("/editor")) {
        window.location.assign("/")
        return
      }
      router.push("/")
      return
    }
    if (typeof window !== "undefined" && window.location.pathname.startsWith("/editor")) {
      window.location.assign("/login")
      return
    }
    router.push("/login")
  }

  const { openBuyCoins } = useBuyCoins()

  const profileUser = user
    ? {
        name: displayNameFromEmail(user.email),
        email: user.email,
        avatarUrl: null as string | null,
      }
    : undefined

  return (
    <div
      className={cn(
        "flex min-h-dvh flex-col bg-transparent",
        variant === "editor" && "h-dvh max-h-dvh overflow-hidden"
      )}
    >
      <AppHeader
        user={profileUser}
        onLogout={handleLogout}
        showBreadcrumbs={variant === "workspace"}
        coins={user?.ai_coins}
        onBuyCoins={openBuyCoins}
      />
      <main
        className={cn(
          "flex min-h-0 min-w-0 flex-1 flex-col",
          variant === "workspace" && "overflow-x-hidden px-4 py-6 sm:px-6 lg:px-8",
          variant === "editor" && "overflow-hidden"
        )}
      >
        {children}
      </main>
    </div>
  )
}

export { AppShell }
export type { AppShellProps }
