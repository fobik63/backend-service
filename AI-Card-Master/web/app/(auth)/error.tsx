"use client"

import Link from "next/link"
import { useEffect } from "react"

import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type AuthErrorProps = {
  error: Error & { digest?: string }
  reset: () => void
}

export default function AuthError({ error, reset }: AuthErrorProps) {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[auth-error]", error)
    }
  }, [error])

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 px-6 text-center text-foreground">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        Авторизация
      </p>
      <h1 className="max-w-md font-heading text-2xl font-semibold tracking-tight">
        Ошибка экрана входа
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        {error.message || "Не удалось загрузить форму. Попробуйте ещё раз."}
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
          href="/login"
          className={cn(buttonVariants({ size: "default", variant: "outline" }))}
        >
          Ко входу
        </Link>
      </div>
    </main>
  )
}
