import type { ReactNode } from "react"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

import { Footer } from "@/components/landing/footer"

type LegalPageShellProps = {
  title: string
  updatedAt: string
  children: ReactNode
}

function LegalPageShell({ title, updatedAt, children }: LegalPageShellProps) {
  return (
    <div className="relative min-h-dvh overflow-x-hidden text-foreground">
      <header className="mx-auto flex max-w-3xl items-center px-5 pt-8 pb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-loft-surface px-3 py-2 text-sm text-foreground/90 transition-colors hover:border-white/20"
        >
          <ArrowLeft className="size-4 text-muted-foreground" aria-hidden />
          На главную
        </Link>
      </header>

      <main className="mx-auto max-w-3xl px-5 pb-16 pt-6">
        <p className="font-heading text-xs font-medium tracking-[0.18em] text-muted-foreground uppercase">
          CARD AI
        </p>
        <h1 className="mt-2 font-heading text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          {title}
        </h1>
        <p className="mt-3 text-sm text-text-muted">
          Обновлено: {updatedAt}
        </p>
        <div className="mt-4 h-px w-12 bg-white/30" />

        <article className="prose-legal mt-10 space-y-6 text-sm leading-relaxed text-text-muted sm:text-base">
          {children}
        </article>
      </main>

      <Footer />
    </div>
  )
}

export { LegalPageShell }
