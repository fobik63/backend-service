"use client"

import { Menu, X } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"
import { AnimatePresence, motion } from "framer-motion"

import { AuthModal } from "@/components/modals/auth-modal"
import { GlassButton } from "@/components/ui/glass-button"
import { cn } from "@/lib/utils"

const NAV_LINKS = [
  { href: "#features", label: "Возможности" },
  { href: "#pricing", label: "Тарифы" },
  { href: "#testimonials", label: "Отзывы" },
  { href: "#faq", label: "FAQ" },
  { href: "#cta", label: "Начать" },
] as const

function scrollToHash(hash: string) {
  const id = hash.replace(/^#/, "")
  const el = document.getElementById(id)
  if (!el) return false
  el.scrollIntoView({ behavior: "smooth", block: "start" })
  window.history.replaceState(null, "", `#${id}`)
  return true
}

function CardLogoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden
    >
      <rect
        x="3.5"
        y="5"
        width="17"
        height="22"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-copper/80"
      />
      <rect
        x="7.5"
        y="1"
        width="17"
        height="22"
        rx="2.5"
        fill="rgba(22,24,30,0.9)"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-emerald"
      />
      <path
        d="M11 8.5h10M11 12.5h7M11 16.5h8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        className="text-copper/70"
      />
      <circle cx="21.5" cy="5.5" r="2" className="fill-emerald" />
    </svg>
  )
}

function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [mobileOpen])

  const openAuth = () => {
    setMobileOpen(false)
    setAuthOpen(true)
  }

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-5">
      <nav
        className={cn(
          "pointer-events-auto mx-auto flex max-w-6xl items-center justify-between gap-4 rounded-2xl px-4 py-3 transition-[box-shadow,border-color] duration-300 sm:px-5",
          "glass-panel",
          scrolled && "border-white/12 shadow-[0_12px_40px_rgba(0,0,0,0.35)]"
        )}
        aria-label="Главная навигация"
      >
        <Link
          href="/landing"
          className="group flex shrink-0 items-center gap-2.5"
        >
          <CardLogoIcon className="size-7 transition-transform duration-300 group-hover:scale-105" />
          <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
            CARD AI
            <span
              aria-hidden
              className="ml-0.5 inline-block size-1.5 translate-y-[-0.35em] rounded-full bg-foreground"
            />
          </span>
        </Link>

        <ul className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                className="rounded-lg px-3 py-2 text-sm text-text-muted transition-colors hover:text-foreground"
                onClick={(e) => {
                  if (scrollToHash(link.href)) e.preventDefault()
                }}
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>

        <div className="hidden items-center gap-2 sm:flex">
          <GlassButton
            size="default"
            className="border border-white/12 bg-transparent text-foreground"
            onClick={openAuth}
          >
            Войти
          </GlassButton>
          <GlassButton size="default" onClick={openAuth}>
            Попробовать бесплатно
          </GlassButton>
        </div>

        <button
          type="button"
          className="inline-flex size-10 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-foreground md:hidden"
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav"
          aria-label={mobileOpen ? "Закрыть меню" : "Открыть меню"}
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </nav>

      <AnimatePresence>
        {mobileOpen ? (
          <motion.div
            id="mobile-nav"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="pointer-events-auto mx-auto mt-2 max-w-6xl overflow-hidden rounded-2xl glass-panel md:hidden"
          >
            <ul className="flex flex-col gap-1 p-3">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    className="block rounded-lg px-3 py-2.5 text-sm text-text-muted transition-colors hover:bg-white/[0.04] hover:text-foreground"
                    onClick={(e) => {
                      setMobileOpen(false)
                      if (scrollToHash(link.href)) e.preventDefault()
                    }}
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
            <div className="flex flex-col gap-2 border-t border-white/8 p-3 sm:hidden">
              <GlassButton
                className="w-full border border-white/12 bg-transparent text-foreground"
                onClick={openAuth}
              >
                Войти
              </GlassButton>
              <GlassButton className="w-full" onClick={openAuth}>
                Попробовать бесплатно
              </GlassButton>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AuthModal open={authOpen} onOpenChange={setAuthOpen} initialMode="otp" />
    </header>
  )
}

export { Navbar }
