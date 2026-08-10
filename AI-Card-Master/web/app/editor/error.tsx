"use client"

import Link from "next/link"
import { useEffect } from "react"

import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type EditorErrorProps = {
  error: Error & { digest?: string }
  reset: () => void
}

export default function EditorError({ error, reset }: EditorErrorProps) {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[editor-error]", error)
    }
  }, [error])

  return (
    <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 bg-transparent px-6 text-center text-foreground">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        Редактор
      </p>
      <h1 className="max-w-md font-heading text-2xl font-semibold tracking-tight">
        Не удалось загрузить редактор
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        {error.message ||
          "Состояние проекта не инициализировано или данные товара недоступны."}
      </p>
      {error.digest ? (
        <p className="font-mono text-[11px] text-muted-foreground/70">
          digest: {error.digest}
        </p>
      ) : null}
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
            window.location.assign("/projects")
          }}
          className={cn(buttonVariants({ size: "default", variant: "outline" }))}
        >
          Назад в проекты
        </Link>
      </div>
    </main>
  )
}
