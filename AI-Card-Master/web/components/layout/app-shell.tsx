"use client"

import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { AppHeader } from "@/components/layout/app-header"
import { fetchCurrentUser } from "@/lib/api/auth"
import {
  displayNameFromEmail,
  persistSession,
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
        const refresh =
          typeof window !== "undefined"
            ? window.localStorage.getItem("refresh_token")
            : null
        if (refresh) {
          persistSession(
            { access_token: accessToken, refresh_token: refresh },
            profile,
          )
        }
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
      router.push("/projects")
      return
    }
    router.push("/login")
  }

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
        variant === "editor" && "h-dvh overflow-hidden"
      )}
    >
      <AppHeader
        user={profileUser}
        onLogout={handleLogout}
        showBreadcrumbs={variant === "workspace"}
      />
      <main
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          variant === "workspace" && "px-4 py-6 sm:px-6 lg:px-8"
        )}
      >
        {children}
      </main>
    </div>
  )
}

export { AppShell }
export type { AppShellProps }
