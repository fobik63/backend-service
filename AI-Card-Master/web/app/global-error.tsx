"use client"

import { useEffect } from "react"

type GlobalErrorProps = {
  error: Error & { digest?: string }
  reset: () => void
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[global-error]", error)
    }
  }, [error])

  return (
    <html lang="ru" className="dark">
      <body className="bg-[#0d0f12] font-sans antialiased text-foreground">
        <main className="flex min-h-svh flex-col items-center justify-center gap-4 px-6 text-center">
          <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
            Критическая ошибка
          </p>
          <h1 className="max-w-md text-2xl font-semibold tracking-tight text-foreground">
            Приложение не смогло продолжить работу
          </h1>
          <p className="max-w-sm text-sm text-muted-foreground">
            {error.message || "Неизвестная ошибка клиента. Попробуйте перезагрузить страницу."}
          </p>
          {error.digest ? (
            <p className="font-mono text-[11px] text-muted-foreground/70">
              digest: {error.digest}
            </p>
          ) : null}
          <button
            type="button"
            onClick={reset}
            className="mt-2 inline-flex h-9 items-center justify-center rounded-lg bg-emerald px-4 text-sm font-medium text-loft transition-opacity hover:opacity-90"
          >
            Попробовать снова
          </button>
        </main>
      </body>
    </html>
  )
}
