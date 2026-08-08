import type { ReactNode } from "react"
import Link from "next/link"
import { ArrowLeft, X } from "lucide-react"

type AuthLayoutProps = {
  children: ReactNode
}

export default function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-loft px-4 py-10">
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute -left-24 top-1/4 size-72 rounded-full bg-emerald/15 blur-3xl" />
        <div className="absolute -right-20 bottom-1/4 size-80 rounded-full bg-[#1b3e2b]/50 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(16,185,129,0.12),transparent_55%)]" />
        <div
          className="absolute inset-0 opacity-[0.04] noise-texture"
          aria-hidden
        />
      </div>

      <Link
        href="/landing"
        className="absolute top-5 left-5 z-20 inline-flex items-center gap-2 rounded-lg border border-white/10 bg-loft-surface/80 px-3 py-2 text-sm text-foreground/90 shadow-lg backdrop-blur-md transition-colors hover:border-copper/40 hover:bg-loft-surface"
      >
        <ArrowLeft className="size-4 text-copper" aria-hidden />
        Назад на главную
      </Link>

      <Link
        href="/landing"
        aria-label="Закрыть и вернуться на главную"
        className="absolute top-5 right-5 z-20 inline-flex size-10 items-center justify-center rounded-full border border-white/10 bg-loft-surface/80 text-foreground/80 shadow-lg backdrop-blur-md transition-colors hover:border-copper/40 hover:text-foreground"
      >
        <X className="size-4" />
      </Link>

      <div className="relative z-10 w-full max-w-md">{children}</div>
    </div>
  )
}
