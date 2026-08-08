import type { ReactNode } from "react"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

type AuthLayoutProps = {
  children: ReactNode
}

export default function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10">
      <Link
        href="/landing"
        className="absolute top-5 left-5 z-20 inline-flex items-center gap-2 rounded-lg border border-white/10 bg-loft-surface/80 px-3 py-2 text-sm text-foreground/90 shadow-lg backdrop-blur-md transition-colors hover:border-copper/40 hover:bg-loft-surface"
      >
        <ArrowLeft className="size-4 text-copper" aria-hidden />
        Назад на главную
      </Link>

      <div className="relative z-10 w-full max-w-md">{children}</div>
    </div>
  )
}
