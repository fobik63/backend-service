"use client"

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useState, type ReactNode } from "react"

import { ProfileSheet } from "@/components/dashboard/profile-sheet"
import { Sidebar } from "@/components/dashboard/sidebar"
import { TopBar } from "@/components/dashboard/top-bar"
import { TopUpDialog } from "@/components/dashboard/top-up-dialog"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type DashboardShellProps = {
  children: ReactNode
}

function DashboardShell({ children }: DashboardShellProps) {
  const { t } = useI18n()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [topUpOpen, setTopUpOpen] = useState(false)

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

  return (
    <div className="flex min-h-dvh bg-transparent">
      <div className="hidden lg:fixed lg:inset-y-0 lg:z-30 lg:flex">
        <Sidebar onOpenProfile={openProfile} onTopUp={openTopUp} />
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
          onMenuClick={() => setMobileOpen(true)}
          onOpenProfile={openProfile}
        />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>

      <ProfileSheet open={profileOpen} onOpenChange={setProfileOpen} />
      <TopUpDialog open={topUpOpen} onOpenChange={setTopUpOpen} />
    </div>
  )
}

export { DashboardShell }
