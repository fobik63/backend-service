"use client"

import { AnimatePresence, motion } from "framer-motion"
import { useRouter } from "next/navigation"
import { useEffect, useState, type ReactNode } from "react"

import { ProfileSheet } from "@/components/dashboard/profile-sheet"
import { Sidebar } from "@/components/dashboard/sidebar"
import { TopBar } from "@/components/dashboard/top-bar"
import { TopUpDialog } from "@/components/dashboard/top-up-dialog"
import { fetchCurrentUser } from "@/lib/api/auth"
import {
  displayNameFromEmail,
  persistSession,
  subscriptionLabel,
} from "@/lib/auth/session"
import { IS_MOCK, MOCK_AUTH_USER } from "@/lib/constants/mock"
import { useI18n } from "@/lib/i18n"
import { useAuthStore } from "@/lib/store"
import { cn } from "@/lib/utils"

type DashboardShellProps = {
  children: ReactNode
}

function DashboardShell({ children }: DashboardShellProps) {
  const { t } = useI18n()
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const hydrated = useAuthStore((s) => s.hydrated)
  const hydrateFromStorage = useAuthStore((s) => s.hydrateFromStorage)
  const setUser = useAuthStore((s) => s.setUser)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  const [mobileOpen, setMobileOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [topUpOpen, setTopUpOpen] = useState(false)

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

  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [mobileOpen])

  useEffect(() => {
    if (!mobileOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [mobileOpen])

  const openProfile = () => {
    setMobileOpen(false)
    setProfileOpen(true)
  }

  const openTopUp = () => {
    setMobileOpen(false)
    setTopUpOpen(true)
  }

  const handleLogout = () => {
    clearAuth()
    if (IS_MOCK) {
      router.push("/dashboard")
      return
    }
    router.push("/login")
  }

  const profileUser = user
    ? {
        name: displayNameFromEmail(user.email),
        email: user.email,
        avatarUrl: null as string | null,
        statusLabel: subscriptionLabel(user.subscription_status),
      }
    : undefined

  const balance = user
    ? { current: user.ai_coins, limit: Math.max(user.ai_coins, 50) }
    : undefined

  return (
    <div className="flex min-h-dvh bg-transparent">
      <div className="hidden lg:fixed lg:inset-y-0 lg:z-30 lg:flex">
        <Sidebar
          user={
            profileUser
              ? {
                  name: profileUser.name,
                  avatarUrl: profileUser.avatarUrl,
                  statusLabel: profileUser.statusLabel,
                }
              : undefined
          }
          balance={balance}
          onOpenProfile={openProfile}
          onTopUp={openTopUp}
        />
      </div>

      <AnimatePresence>
        {mobileOpen ? (
          <>
            <motion.button
              type="button"
              aria-label={t("common.closeMenu")}
              className="fixed inset-0 z-40 bg-black/55 lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={() => setMobileOpen(false)}
            />
            <motion.div
              className="fixed inset-y-0 left-0 z-50 lg:hidden"
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", stiffness: 380, damping: 36 }}
            >
              <Sidebar
                user={
                  profileUser
                    ? {
                        name: profileUser.name,
                        avatarUrl: profileUser.avatarUrl,
                        statusLabel: profileUser.statusLabel,
                      }
                    : undefined
                }
                balance={balance}
                onNavigate={() => setMobileOpen(false)}
                onOpenProfile={openProfile}
                onTopUp={openTopUp}
              />
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>

      <div className={cn("flex min-h-dvh flex-1 flex-col lg:pl-64")}>
        <TopBar
          user={
            profileUser
              ? {
                  name: profileUser.name,
                  email: profileUser.email,
                  avatarUrl: profileUser.avatarUrl,
                }
              : undefined
          }
          onMenuClick={() => setMobileOpen(true)}
          onOpenProfile={openProfile}
          onLogout={handleLogout}
        />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>

      <ProfileSheet
        open={profileOpen}
        onOpenChange={setProfileOpen}
        user={profileUser}
        balance={balance}
        onLogout={handleLogout}
      />
      <TopUpDialog open={topUpOpen} onOpenChange={setTopUpOpen} />
    </div>
  )
}

export { DashboardShell }
