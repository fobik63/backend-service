"use client"

import Link from "next/link"
import { useEffect } from "react"

import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type DashboardErrorProps = {
  error: Error & { digest?: string }
  reset: () => void
}

export default function DashboardError({ error, reset }: DashboardErrorProps) {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[dashboard-error]", error)
    }
  }, [error])

  return (
    <main className="flex min-h-[60svh] flex-col items-center justify-center gap-4 px-6 text-center text-foreground">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        Кабинет
      </p>
      <h1 className="max-w-md font-heading text-2xl font-semibold tracking-tight">
        Не удалось загрузить раздел
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        {error.message || "Попробуйте обновить страницу или вернуться к проектам."}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={reset}
          className={cn(buttonVariants({ size: "default" }))}
        >
          Попробовать снова
        </button>
        <Link
          href="/projects"
          className={cn(buttonVariants({ size: "default", variant: "outline" }))}
        >
          К проектам
        </Link>
      </div>
    </main>
  )
}
